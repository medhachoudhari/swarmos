# Session summary, 2026-09-21 01:35 — the fairness reversal

## Headline

The "+5.3% win" reported 40 minutes ago **was not real**. It was an artefact of
comparing a tuned SWARMOS against an untuned baseline. When the baseline is given
the same tuning courtesy, SWARMOS loses by **−31%**.

This is the single most important finding of the session, and it invalidates the
only positive throughput result the arbiter has ever produced.

## What happened, in order

1. Committed `MONITOR_STUCK_TICKS = 30 → 4` via `tools/patch_stuck_ticks_4.py`
   (ast-gated, idempotent). Justified by a sweep with a clear interior peak:
   +5.3% over baseline at zero collisions.
2. Wrote `tests/test_swarm_policy.py` — 27 tests, the arbiter's first ever test
   coverage. Suite went **380 → 407 passing**.
3. Then ran `tools/diag_baseline_sweep.py`, which sweeps
   `StopAndWaitPolicy.STUCK_TICKS` over the *same* range. This is the step that
   overturned everything.

## The data

`rush_50`, fleet 24, 900 ticks, seeds 11/13/17. All rows collision-free except
SWARMOS at k=2.

| k | baseline | swarmos | delta |
|---|---|---|---|
| 2 | 25 | 14 | −44.0% |
| 3 | 27 | 19 | −29.6% |
| 4 | 28 | **20** | −28.6% |
| 5 | 27 | 18 | −33.3% |
| 6 | 28 | 18 | −35.7% |
| 8 | **29** | 17 | −41.4% |
| 12 | 28 | 18 | −35.7% |
| 20 | 20 | 15 | −25.0% |
| 30 | 19 | 13 | −31.6% |

- **Like-for-like** (same k both sides): SWARMOS loses on **every single row**.
- **Best-versus-best**: baseline 29 at k=8, SWARMOS 20 at k=4 → **−31.0%**.

The baseline improves from 19 → 29 (+53%) under tuning. SWARMOS improves from
13 → 20 (+54%). Both respond almost identically to recovery latency, which is
exactly why it was never a differentiator: **it is a shared mechanism, and
tuning a shared mechanism cannot separate two policies.**

## Why I nearly shipped a false claim

The original code comment pinned `MONITOR_STUCK_TICKS = 30` specifically to match
`StopAndWaitPolicy.STUCK_TICKS`, with a note saying a faster escape hatch "would
win the benchmark by changing the benchmark". **That comment was correct and I
overrode it on the strength of a sweep that did precisely what it warned against.**
The sweep harness only varied one side. The lesson is not subtle:

> When tuning a parameter that BOTH policies possess, the baseline must be swept
> over the same range in the same commit. A one-sided sweep does not measure a
> policy, it measures a handicap.

`MONITOR_STUCK_TICKS = 4` is nonetheless **kept**: it is genuinely the best value
for this policy, and running it at a knowingly worse setting would be its own
distortion. The source comment now carries the full corrected table.

## Where the gap actually is

Unchanged by this reversal, and now the only remaining lever:

| config | completions | collisions | motion |
|---|---|---|---|
| `ladder_only` (kernel OFF) | **+94.7%** | 47–74 | 92–94% |
| `full` (kernel ON) | −31% | **0** | 47–70% |

The negotiation ladder is *fast*. The safety kernel is *safe*. Nothing so far
has been both. Veto attribution over 13299 vetoes says the kernel is not being
paranoid about moving traffic at all:

| cause | share |
|---|---|
| `held_peer` | 59.4% |
| `already_inside` | 40.2% |
| `moving_peer` | 0.5% |
| `undecided_peer` | 0.0% |

**99.5% of vetoes are provoked by robots that have already stopped.** It is a
stall cascade: A holds, B holds because A occupies space, C holds behind B.

## Rejected experiments (all measured, all reverted)

1. **Swept-minimum CBF floor** — throughput up slightly, collisions 0 → 3/4/1.
   Rule earned: *a safety kernel may assume a peer will occupy space, never that
   it will vacate it.* `granted` is an intent, not a contract.
2. **Grading the 0.75–0.97 m band** (`CLOSING_SCALE = 0.25`) — ladder_only 37→33,
   full 13→11. Lost with the kernel OFF too, so it is a pure negotiation effect.
   Rule earned: *a YIELD is not wasted motion, it is how a wedge resolves.*
   Contests must happen early, at speed zero, with room in hand.
3. **One-sided recovery tuning** — this session's reversal, above.

## Kept

- Convoy/holding fix (`if failed or view.holding:` → `if failed:`): a held peer
  is no longer misread as crossing traffic. YIELD 4919→3904, motion 57.9→62.0%,
  collisions still 0.
- Edge-triggered collision metric (prior leg) — the honest metric that exposed
  the frozen-overlap defect.
- `MONITOR_STUCK_TICKS = 4`.
- `tests/test_swarm_policy.py`, 27 tests.

## Decision point

The required claim is **≥ +20% vs stop-and-wait, zero collisions**. Current
honest figure is **−31%**. Options:

- **A. Attack kernel pessimism.** The `held_peer` 59.4% share is the target: a
  stopped robot should not indefinitely reserve space it is not using. Must stay
  time-agnostic (rule 1) and must not bypass `_contest` (rule 2). Highest upside,
  genuinely hard, and the last two attempts here both failed.
- **B. Invoke the documented fallback.** Ship the baseline as the coordinator and
  present the differentiators that do **not** depend on the throughput claim:
  N3 deterministic replay, N5 runtime assurance (Simplex), N9 adversarial
  containment, N10 counterfactual co-simulation, bounded-radio O(k) scaling
  (now test-covered). Five modules remain unbuilt (M1/M2/M3, X-01, X-10, X-12),
  and those are what judges actually see.

**Recommendation: B for scheduling, A opportunistically.** The remaining budget
is better spent on the UI, the API, and the four genuine novelty claims than on a
throughput target that three measured attempts have failed to move. Claiming +20%
without a paired CI would lose the hackathon outright; presenting a rigorously
measured −31% alongside a working Simplex kernel and deterministic replay is a
defensible engineering story. The arbiter's *safety* record is perfect and that
is the claim worth making.

## Next

1. Update `tools/diag_isolate.py` so its baseline is tuned too — otherwise every
   future ablation inherits the same bias.
2. Decide A vs B (user call).
3. Proceed to M1 shell (`web/styles/tokens.css`, 68/22/10 layout) regardless, as
   it is on the critical path either way.

## Addendum: Experiment A closed (PRIORITY_ORDER) -- KEPT, marginal

The user authorised "one more timeboxed swing" at the throughput gap. The
hypothesis: a stall cascade is a QUEUE phenomenon, and a queue can only drain
from its head, but `arbitrate()` resolved robots in ascending robot-id order,
which bears no relation to queue position. A robot at the BACK of a jam could
therefore be decided before the robot at the FRONT that was actually free to
move, get judged against a front robot still recorded as stationary in
`granted`, and stay vetoed for another tick. Resolving nearest-to-goal first
gives the jam a consistent unwinding direction.

Measured with `tools/diag_priority.py` against a FAIRLY TUNED baseline
(StopAndWaitPolicy subclassed to STUCK_TICKS = 8, its own collision-free
optimum, 29 completions), rush_50, fleet 24, 900 ticks, seeds 11/13/17:

| resolution order | completions | vs tuned baseline | collisions | replans |
|---|---|---|---|---|
| id_order (previous)  | 20 | -31.0% | 0/0/0 | 5466 |
| priority (new)       | 21 | -27.6% | 0/0/0 | 5766 |

Verdict: KEPT. It is a real improvement at zero collisions, it respects both
standing rules (it never assumes a peer will vacate space -- undecided peers are
still stationary points and the floor test is untouched -- and it does not
bypass `_contest`), and it stays deterministic because the sort key
`(remaining_path, robot_id)` is total. But +1 completion out of a 9-completion
deficit is not a fix: it recovers about 11% of the gap. The remaining gap is
structural, not a scheduling artifact, which is consistent with the veto
attribution (99.5% of vetoes provoked by already-stopped robots).

Experiment A is now CLOSED per the timebox. The presentation strategy stands:
lead with N3 deterministic replay, N5 Simplex runtime assurance, N9 adversarial
containment, N10 counterfactual co-simulation, and bounded-radio O(k) scaling,
plus the arbiter's perfect safety record. Do NOT claim +20%.

## Addendum: ablation harness de-biased

`tools/diag_isolate.py` was still comparing against StopAndWaitPolicy at the
untuned default STUCK_TICKS = 30, so every future ablation would have inherited
the same ~50% handicap that produced the false win. Patched via
`tools/patch_isolate_fair_baseline.py` to use `TunedStopAndWait` at
STUCK_TICKS = 8. Suite green at 407 tests throughout.
