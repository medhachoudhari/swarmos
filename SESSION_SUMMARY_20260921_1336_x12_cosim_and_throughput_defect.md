# Session summary, 2026-09-21 13:36 - X-12 co-simulation lands, and immediately finds a project-level defect

Task chosen by the user: **"X-12 next"** (counterfactual co-simulation, novelty
claim N10). It is built and working. Its first honest measurement says the
product does not currently do the main thing it claims.

## 1. What was built: `app/sim/cosim.py` (NEW, ~330 lines)

Two `SimEngine` instances stepped in lockstep from the **identical scenario
object and identical seed** - one driven by `SwarmPolicy`, one by the tuned
`StopAndWaitPolicy` ghost. Since `app/sim/tasks.py` derives the task stream from
the seed alone, both arms get the same warehouse, same orders, same ticks, same
faults; only the coordination policy differs. That is what makes it a
counterfactual rather than two simulations side by side.

Key members: `CoSimulation` (`.step()`, `.run(n)`, `.inject(kind)` - which
applies to BOTH arms deliberately, `.summary()`, `.last_frame()`,
`.static_payload()`, `.tick`, `.in_lockstep`, `.divergence_tick`),
`ArmFrame`, `KpiDelta`, `compare_kpis()`, `make_baseline_policy()`,
`make_treatment_policy()`, `HEADLINE_KPIS`, `LOWER_IS_BETTER`,
`BASELINE_STUCK_TICKS = 8` (duplicated, not imported: `app/sim` must not
depend on `app/api`).

Design notes worth keeping:
- `divergence_tick` records the FIRST tick the arms' `tasks_complete` disagree,
  written once and never overwritten. `None` means the worlds are still identical.
- Compute is reported per arm AND summed against the 100 ms budget, with a
  `breaches` count. Two engines per tick is twice the work; the budget is a
  property of ONE controller, so the honest move is to report the sum rather
  than quietly redefine the budget. Measured: **8.76 + 2.94 = 11.69 ms**, no breaches.
- A KPI absent from either arm is skipped, not defaulted to 0 - a zero would
  read as "they tied", which is a different claim from "not measured". Skipped
  names are exposed via `compare_kpis.missing` so the UI can render `--`.

## 2. THE DEFECT X-12 EXISTS TO CATCH, and it is ours

`rush_50`, fleet 50, 900 ticks, seeds 11/13/17, same seed both arms:

| arm | seed 11 | seed 13 | seed 17 | TOTAL | collisions |
|---|---|---|---|---|---|
| baseline (stop-and-wait) | 9 | 3 | 10 | **22** | 0 / 0 / 0 |
| swarmos (full) | 5 | 3 | 3 | **11** | 1 / 3 / 0 |

**SWARMOS completes half the tasks of the strawman it is built to beat**, and at
1800 ticks the gap is worse: 5 vs 21. `tasks_per_min` is the hero metric on the
dashboard. Right now that metric, honestly measured, says we lose.

Attribution (900 ticks, seeds 11/17):

| config | completions | collisions | reroutes | vetoes/tick |
|---|---|---|---|---|
| baseline | 9 / 10 | 0 / 0 | 1299 / 2078 | 12.47 / 19.23 halts |
| ladder_only (`monitor=False`) | **22 / 23** | **223 / 218** | 123 / 120 | 0 |
| full | 1 / 2 | 0 / 0 | 2837 / 3384 | 12.58 / 14.92 |

This is the clean statement of the problem: **the negotiation ladder beats the
baseline 2.4x, and the safety kernel that makes it collision-free costs 95% of
its throughput.** Note the halt RATES are almost identical between baseline and
full (12.58 vs 12.47 per tick) - so it is not that the monitor stops more
robots. It is that `full` reroutes **2.2x** as often. The cost is replan churn:
robots are held, hit `MONITOR_STUCK_TICKS`, throw away their path, replan into
another held pair, and repeat.

## 3. REJECTED: non-degradation floor (`tools/patch_nondegrade_floor.py`, reverted)

Hypothesis, from the KNOWN LIMITATION in `_monitor`'s own docstring: `swept(scale)`
always contains `here`, so `gap <= at_rest` for every scale, so once a pair is
inside `HARD_STOP_M` **no** fraction of the step clears it and the graded
`MONITOR_SCALES` fallback is dead - every intervention becomes a full stop.
Fix tried: floor becomes `min(at_rest, HARD_STOP_M)`, i.e. "do not make it worse"
instead of "clear a bar you cannot reach".

I believed this was distinct from the three rejected "gap is opening" exemptions
(those were ENDPOINT tests, which cannot tell separating from crossing; this is
measured on the same SEGMENT distance, and crossing paths have segment distance
0) and distinct from the rejected time-parameterised test (no shared time
parameter, no assumption the peer vacates anything).

**Measured: total 11 completions - unchanged - AND it introduced 1 and 3
collisions where there had been 0.** No throughput gain, safety lost. Reverted
from `/tmp/swarm_policy.before_nondegrade.py`; 503 tests pass, `NONDEGRADE_EPS_M`
gone, KNOWN LIMITATION note restored.

**Lesson: the dead graded fallback was NOT the throughput limiter.** It is a real
defect and it is still there, but fixing it does not buy completions. I had
assumed the two were the same problem because they live in the same function.

## 4. Also rejected: tuning `MONITOR_STUCK_TICKS`

Sweep at fleet 50, 3 seeds, total completions / total collisions:

| MONITOR_STUCK_TICKS | completions | collisions | reroutes (s11) |
|---|---|---|---|
| 4 (current) | 6 | 1 | 2837 |
| 8 | **12** | 2 | 1361 |
| 16 | 8 | 1 | 864 |
| 40 | 6 | 0 | 333 |

8 doubles throughput and confirms replan churn is implicated, but it still loses
to baseline's 22 and it buys collisions. **Not taken**: a parameter change that
trades our one unambiguous win (zero collisions) for a metric we still lose is
not a fix. The non-monotonic shape (6, 12, 8, 6) says the mechanism is a
genuine research problem, not a knob mis-set.

## 5. Two defects fixed in my own new file

`tools/patch_cosim_compute.py`:
1. `compute_ms` was read as `kpis()["compute"]["last_ms"]`. **No such key** -
   `compute_ms` is TOP-level; the nested `compute` dict holds the p50/p95/p99
   distribution. The `.get` chain returned a silent `0.0`, so every compute
   number the co-simulation reported was fabricated. Exactly the fake-data class
   the UI rules forbid, in the module whose whole job is honest measurement.
2. `p95_completion_s` silently vanished from the delta table (absent from
   `kpis()` until a task completes). Now recorded in `compare_kpis.missing`.

## 6. State

- **503 tests pass** (95 s), verified after the revert. Frontend gate untouched this leg.
- `app/sim/cosim.py` works headless and is correct as far as measured.
- `app/coordination/swarm_policy.py` is byte-restored to its pre-leg state.
- Server still running on port 8770 (user's terminal). Untouched.

## 7. Next step, and a scope judgement

The X-12 UI is **deliberately not built yet.** Wiring a side-by-side view right
now would render a large, well-designed panel whose headline number says we lose
to a strawman. The panel is easy; the number is the product.

Recommended order:
1. **Fix the monitor/ladder throughput trade-off.** The lead is replan churn, not
   halting: `full` reroutes 2.2x baseline at the same halt rate. Likely direction -
   a held robot should keep its path and wait rather than discard and replan, and
   `_contest`'s aging should break the wedge instead of `MONITOR_STUCK_TICKS`.
   Target: beat baseline's 22 with collisions at 0.
2. Then tests for `cosim.py`, then the API/WS wiring, then the side-by-side UI.
3. `run.sh` and `README.md` still do not exist.

Honest note for the BEL demo either way: "our safety kernel is provably
collision-free and we can show you exactly what it costs" is a defensible
engineering story, and X-12 is what lets us tell it with numbers instead of
adjectives. But it is a much better story if the cost is small.

---

## 8. Addendum 13:45 - two more rejected fixes, and the scaling curve that reframes the problem

### 8.1 REJECTED: lowering `HARD_STOP_M`

Hypothesis: with `MAX_STEP_M` 0.22 added to the 0.75 m floor the effective veto
radius is ~0.97 m against a **1.0 m aisle pitch**, so a robot one aisle over - never
on a converging course - sits permanently inside the floor. That is exactly the
version-4 defect the `_monitor` docstring records, reappearing through the swept
segment rather than through a point test.

| `HARD_STOP_M` | completions (3 seeds) | collisions | monitor vetoes |
|---|---|---|---|
| 0.75 (current) | 6 | **1** | 11319 / 10556 / 13424 |
| 0.70 | 10 | 19 | 10012 / 12309 / 12329 |
| 0.60 | 7 | 264 | 10707 / 12660 / 12554 |
| 0.50 | 6 | 262 | 11161 / 13443 / 11156 |

Rejected: collisions explode and completions never approach baseline's 22.

**The important number here is the veto column: it barely moves - 10k to 13k -
while the floor shrinks by a third.** If the floor's SIZE were generating the
vetoes, shrinking it would cut them. It does not. So the vetoes are not an
artifact of a too-wide floor, and the aisle-pitch hypothesis is wrong. The fleet
is genuinely, persistently in conflict.

Corroborating measurement, `full`, seed 11, end of a 900-tick run: **40 of 50
robots held, but only 14 have a peer inside the floor.** 36 still hold a path and
all 40 still hold a task. So most held robots are not in a pairwise standoff at
all - they are queued behind one, which is why local fixes to the pairwise test
keep failing to move the number.

### 8.2 The scaling curve (the useful result)

Same seeds, same 900 ticks, only `fleet_size` varies:

| fleet | swarmos | baseline | swarmos collisions |
|---|---|---|---|
| 8 | 10 | 11 | 0 |
| 16 | 16 | 19 | 0 |
| 24 | 21 | 29 | 0 |
| 50 | 6 | 22 | 1 |

At fleet 8 the two are within noise (10 vs 11). The deficit grows with density and
then **collapses** between 24 and 50. This is not a constant handicap from a wrong
constant - it is congestion collapse, and it locates the defect precisely:
somewhere between fleet 24 and 50 the fleet crosses a density threshold where
held robots start blocking each other faster than the recovery can clear them.

That also means the four fixes tried so far were all aimed at the wrong level.
Adjusting the pairwise floor, the graded fallback, or the stuck threshold cannot
fix a queueing collapse; they only change when it starts. The monitor is
**locally correct and globally starving** - a held robot's held-ness is not visible
to the robots queued behind it, so they replan into the same blocked space.

### 8.3 Revised recommendation for the next leg

Do not touch `_monitor`'s pairwise geometry again - four attempts, all measured,
all rejected. The fix has to make congestion visible:

1. **Best lead: a held robot should propagate its held-ness.** `PeerView.holding`
   already exists and is already broadcast. The monitor consumes `granted` but the
   PLANNER does not - `_plan()` reroutes into space occupied by held robots
   because a held robot looks navigable. Making the planner avoid the space behind
   a held peer is a global fix to a global problem, and it costs no safety
   argument because it only ever removes candidate paths.
2. Alternative: cap concurrent active tasks by density, so the fleet is not admitted
   into a state it cannot resolve (`tasks_active` was pinned at exactly 50 of 50 in
   every fleet-50 run - the dispatcher never throttles).
3. Sanity floor: at fleet 8-16 SWARMOS is already at parity and collision-free. If
   the congestion work does not land in time, **demo at fleet 24** - 21 vs 29 with
   zero collisions is an honest, defensible slide; fleet 50 is not.

### 8.4 State at end of leg

`app/coordination/swarm_policy.py` is byte-identical to the start of the leg (all
four experiments reverted; `HARD_STOP_M` and `MONITOR_STUCK_TICKS` sweeps were
done by monkey-patching the module in-process, never by editing the file).
**503 tests pass.** `app/sim/cosim.py` is new, correct, and unwired to the UI.
