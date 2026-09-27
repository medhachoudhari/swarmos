# Session summary, 2026-09-21 00:50 - repairing `_decide`, and two monitor experiments

Continues `SESSION_SUMMARY_20260921_0020_collision_metric_defect.md`. All numbers
below are `rush_50`, fleet 24, 900 ticks, seeds 11/13/17, measured with the
edge-triggered collision metric fixed in the previous leg.

## 1. Repaired the corrupted `_decide` (was blocking everything)

`tools/patch_revert_no_yield.py` had left `app/coordination/swarm_policy.py` with
an `IndentationError` at line 698. Cause: its end anchor
`"        if enc.distance >= CONFLICT_M:\n"` (8 spaces) is also a **suffix** of
the 12-space nested line inside the block it was deleting, so `str.index` matched
at offset 4 and the cut ended mid-block. Every one of its validators passed
because none of them parsed the file. The file is untracked by git, so there was
no safety net.

Fixed by `tools/patch_repair_decide.py`, which restores the ladder verbatim and
**gates on `ast.parse` before writing**. The honest table came back exactly:

| config | completions | vs baseline | collisions |
|---|---|---|---|
| baseline | 19 | +0.0% | 0 / 0 / 0 |
| monitor_only | 13 | -31.6% | 0 / 1 / 1 |
| ladder_only | 37 | +94.7% | 54 / 72 / 47 |
| full | 13 | -31.6% | **0 / 0 / 0** |

That `ast` gate then immediately paid for itself twice - see 3 below.

## 2. Found the arithmetic reason the graded monitor almost never fires

`_monitor.blocked_by` measured `segment_distance(swept(scale), theirs)`, and
`swept(scale)` runs from `here`, so it **always contains `here`**. Therefore

```
segment_distance(swept(scale), theirs) <= segment_distance((here,here), theirs)
```

for every `scale`. So once a pair is inside `HARD_STOP_M`, **no fraction of the
step can clear the floor** and the graded `MONITOR_SCALES` fallback is dead in
precisely the case it was built for. That is the measured `clamp_ratio` of
0.038-0.270: clamping only ever succeeded against peers still approaching from
outside the floor. This is the same "a swept segment contains its own start
point" defect the `_monitor` docstring already records for version 2; the rewrite
inherited it.

**The diagnosis is confirmed and still only partly addressed.** It is the single
most valuable open lead.

## 3. REJECTED: swept-minimum separation + non-degradation floor

`tools/patch_monitor_cbf.py`, reverted by `tools/patch_revert_monitor_cbf.py`.
Replaced the segment test with the exact minimum separation over the tick (convex
in time, closed form) and floored at `min(now, HARD_STOP_M)`.

| config | completions | collisions before -> after |
|---|---|---|
| monitor_only | 13 -> 15 | 0/1/1 -> **5 / 3 / 4** |
| full | 13 -> 14 | 0/0/0 -> **3 / 4 / 1** |

One extra completion across three seeds is noise; the price was destroying the
only genuinely good result, `full` being collision-free. Reverted.

**Why it was unsound, and this is version 3's lesson in disguise.**
`segment_distance` is time-agnostic *on purpose*: it minimises over the two
robots' times independently, so it flags any close approach in **space**,
whoever arrives first. The swept-minimum test parameterises both robots by a
shared time and so can permit a crossing because the pair passes through the
shared space *at different moments*. That is valid only if the peer really
traverses its granted segment at the assumed rate - and it often does not
(replan, path exhausted, its own monitor clamps it after this robot was decided).
`granted` is an **intent, not a contract**.

> Standing rule, now twice-earned: a safety kernel may assume a peer will
> **occupy** space, never that it will **vacate** it. "It will be somewhere else
> by the time I get there" is a vacating assumption with extra arithmetic.
> Any future fix for section 2 must stay time-agnostic.

## 4. KEPT: a held peer is no longer misclassified as crossing traffic

`tools/patch_convoy_holding.py`. `_worst_encounter` had:

```python
if failed or view.holding:
    following = False
```

`view.holding` is set via `_HOLD_KINDS`, which includes `WAIT` - and `WAIT` is
mostly what the **safety monitor** issues, not the negotiation. So the kernel was
coupled back into the ladder through the radio: one clamped leader made every
follower behind it classify as crossing traffic, each yielded to a dead stop,
each of those set its own `holding` bit, and the stall propagated down the aisle.
Enabling the monitor **tripled** the ladder's YIELDs (1568 -> 4919) and cut
motion from 92.6% to 57.9%.

`following` is a question about *direction of travel*, computed from headings. A
clamped peer still has its path and heading and will resume; it has not given up
its turn. So only `failed` now suppresses the convoy rule.

**Not a safety relaxation:** the convoy branch grants `SLOW` at 0.6, never
`PROCEED`, and the monitor is binding and runs after every verdict, so a step
that would truly breach `HARD_STOP_M` is still clamped or held. The ladder is
advisory on separation, so softening a rung cannot create a collision. `_contest`
is untouched, so the aging-based anti-starvation guarantee that the rejected
no-yield-to-stationary patch destroyed is preserved.

Measured effect on `full` (seeds 11/13/17):

| metric | before | after |
|---|---|---|
| YIELD | 4919 / 5714 / 4235 | **3904 / 5541 / 3360** |
| clamp_ratio | 0.175 / 0.173 / 0.270 | **0.284 / 0.203 / 0.429** |
| moving% | 57.9 / 51.5 / 65.3 | 62.0 / 47.1 / **69.8** |
| collisions | 0 / 0 / 0 | **0 / 0 / 0** |
| completions | 13 | 13 |

Kept because the mechanism demonstrably fired - `clamp_ratio` nearly doubled and
YIELDs fell sharply - collisions stayed at zero, and 380 tests still pass.
Completions merely redistributed (seed 11: 2 -> 4, seed 13: 4 -> 2), so this is
a necessary step rather than the win.

## 5. Where the deficit now provably sits

`ladder_only` reaches **+94.7%** at 92-94% motion but 48-74 collisions.
`full` is collision-free at 47-70% motion and -31.6%. The gap is now squarely
**the monitor's ~30-point motion cost**, not the negotiation: the ladder is fast
and unsafe, the kernel is safe and slow, and the whole remaining problem is the
kernel's pessimism.

Two facts bound the search:
- `full` issues 4169-5676 WAITs against `ladder_only`'s **zero**. Nearly all of
  them are monitor vetoes (`vetoes` 3151-5852), not negotiated holds.
- `clamp_ratio` is still only 0.20-0.43, so most interventions remain full stops,
  for the arithmetic reason in section 2.

## 6. Next steps, in priority order

1. Fix section 2 **time-agnostically**. The peer model is the remaining
   pessimism: an undecided peer contributes a POINT at its current position, so
   a robot is judged against a peer that will have moved. A tighter but still
   time-agnostic peer model is the most promising lead.
2. Re-test the version 8 gated exemption (`tools/patch_drop_exemption.py` records
   the exact removed code) now that the metric is honest. Its rejection rested on
   "1 and 3 collisions" under the 470x-inflated metric.
3. Reconsider `MONITOR_STUCK_TICKS = 30` (3 s at 10 Hz) - it is the only
   un-wedging mechanism and 3 s of dead time per wedge is expensive.
4. Write `tests/test_swarm_policy.py`. The arbiter still has **no tests** and
   that is the largest outstanding risk. Must include a regression test for the
   frozen-overlap case the metric defect hid.

**Fallback stands unchanged.** If the arbiter cannot be made to beat the
baseline, ship the baseline as the coordinator and present the differentiators
that do not depend on the throughput claim: N3 deterministic replay, N5 runtime
assurance, N9 adversarial containment, N10 counterfactual co-simulation, bounded
radio O(k) scaling. Claiming 20% without the paired CI would lose outright.

## 7. Process note

Three patch scripts this leg, three outcomes, one lesson each:

- `patch_repair_decide.py` - anchor on text the replacement does **not**
  contain, and never on a string that can be a suffix of a deeper-indented line.
- `patch_monitor_cbf.py` / `patch_revert_monitor_cbf.py` - a measured rejection
  documented in full is worth as much as an accepted patch. The "occupy, never
  vacate" rule is now written down twice.
- `patch_convoy_holding.py` - its **first** version emitted an `else:` whose body
  was only comments. The `ast.parse` gate rejected it and **nothing was
  written**. That is exactly the safeguard whose absence corrupted this file
  earlier. Every patch script now parses before writing, without exception.
