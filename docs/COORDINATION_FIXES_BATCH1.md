# Coordination fixes - batch 1

Date: 2026-09-26. Status: implemented locally, not pushed.

This batch fixes five defects found by a read-only diagnostic of the SWARMOS
vs baseline comparison. It does not touch the baseline policy
(`StopAndWaitPolicy`, `BASELINE_STUCK_TICKS = 8`), the 0.75 m safety floor,
the seeds, the task stream, fleet sizes, durations, the WIP cap, dwell times
or the service radius. The ML layer is untouched and stays outside the safety
path.

## What the diagnostic found

Over 25 paired runs (5 configurations x 5 seeds x 1800 ticks), SWARMOS
completed 175 tasks against the baseline's 335 (-47.8 %), with 0 collisions in
either arm. The dominant mechanism was **permanent wedging**, not over-strict
margins:

1. **Monitor blind spot.** After a replan, waypoint 0 is the centre of the
   robot's current cell, which may lie behind it. The engine drives to
   waypoint 0 first; the monitor checked a straight chord toward a point
   further down the path. Every traced floor entry came from a robot leaving
   that chord. A pair inside the 0.75 m floor can never be granted motion
   again, because every swept segment contains the robot's current position:
   0 of 15 traced pairs ever escaped.
2. **Infeasible contest winners.** The ladder picked the winner on utility
   alone. In 68-91 % of YIELDs the winner did not move, usually because the
   monitor vetoed it on account of the robot yielding to it - a mutual stop.
3. **Head-on losers waited.** In a true head-on, where each robot stands in
   the other's path, the loser held for `YIELD_PATIENCE` ticks before
   replanning.
4. **Backward replans** (shared simulator issue, both arms). 20-45 % of
   replans began by reversing to the cell centre.
5. **Re-dispatch to wedged robots** (shared engine issue, both arms). After a
   stall release the robot, still wedged, received the next task at once.
   At fleet 50, frozen robots held 18 of 30 WIP slots.

## Changes

| Fix | File | Change | Affects |
|---|---|---|---|
| 1 | `app/coordination/swarm_policy.py` | New `_path_prefix`, `swept_geometry`, `geometry_gap`. The monitor now sweeps the true path prefix (the legs the engine will actually drive) **plus** the legacy chord, so it is never weaker than before. The `granted` map publishes the same geometry, so self and peer checks share one envelope. Stale docstring bullet promising a "gap-opening exemption" corrected; there is still no such exemption. | SWARMOS only |
| 2 | `app/coordination/swarm_policy.py` (`_contest`, new `can_pass`, `has_motion`) | Right of way goes to a robot that can actually pass the other. If the utility winner is blocked by the loser and the loser is not blocked by the winner, the outcome is swapped. Pure function of the two broadcast states, so both robots still agree. The commitment still records the utility outcome; feasibility is re-evaluated each tick. Counter `feasibility_swaps`. | SWARMOS only |
| 3 | `app/coordination/swarm_policy.py` (`_contest`, `HEADON_REPLAN_COOLDOWN_TICKS = 20`) | In a genuine head-on (both have motion, each blocks the other), the loser issues REROUTE at once. The engine turns `conflict_with` into an avoid hint. The same pair cannot trigger another immediate replan inside the cooldown; the loser falls back to ordinary YIELD. Counter `headon_replans`. | SWARMOS only |
| 4 | `app/sim/pathfinding.py` (`trim_passed_start`), `app/sim/engine.py` (`_plan`) | Waypoint 0 is dropped only when the robot already lies on the segment from waypoint 0 to waypoint 1, strictly between them. A robot that must go back to the cell centre to turn keeps its path unchanged. | **Both arms** (shared simulator) |
| 5 | `app/sim/engine.py` (`STALL_CLEARANCE_M`, `_held_after_stall`, `_dispatch`, `_check_stalls`) | After a stall release, the robot is not offered new work until no other live robot is within 1.0 m, or until `STALL_RELEASE_TICKS` (150) have passed, whichever comes first. The task is returned to the pool exactly as before; the WIP cap is unchanged. | **Both arms** (shared engine) |

The verdict vocabulary is unchanged (PROCEED, SLOW, YIELD, WAIT, REROUTE), the
monitor still runs after the ladder and is still binding, and nothing is
random.

### Benchmark methodology note

Fixes 4 and 5 live in the simulator, not in any policy, so they change the
**baseline arm's** numbers as well as SWARMOS's. The baseline policy code is
unchanged. Every trace hash changes. Numbers measured before this batch are
not directly comparable with numbers measured after it; the before/after
tables below re-measure both arms on identical conditions.

## Measured result

25 paired runs, seeds 11/13/17/19/23, 1800 ticks each, both arms built
exactly as `app/sim/cosim.py` builds them.

| Configuration | SWARMOS before -> after | Baseline before -> after | Gap before -> after |
|---|---|---|---|
| rush_50 / fleet 8 | 40 -> 41 | 33 -> 44 | +21.2 % -> -6.8 % |
| rush_50 / fleet 16 | 39 -> 47 | 81 -> 65 | -51.9 % -> -27.7 % |
| rush_50 / fleet 50 | 38 -> 67 | 85 -> 83 | -55.3 % -> -19.3 % |
| narrow_aisle_deadlock / 24 | 23 -> 38 | 42 -> 49 | -45.2 % -> -22.4 % |
| blocked_aisle / 40 | 35 -> 67 | 94 -> 97 | -62.8 % -> -30.9 % |
| **All 25** | **175 -> 260** | **335 -> 338** | **-47.8 % -> -23.1 %** |

| Metric (sum over 25 runs) | SWARMOS before -> after | Baseline before -> after |
|---|---|---|
| Collisions | 0 -> 0 | 0 -> 0 |
| Pair-ticks inside the 0.75 m floor | 84,299 -> 0 | 7 -> 5 |
| Stall releases | 3,106 -> 823 | 1,403 -> 751 |
| Robots not moved for 500+ ticks at end (incl. idle) | 451 -> 151 | 271 -> 159 |
| ...of which holding a task | 433 -> 52 | 234 -> 52 |
| WIP slots held by robots frozen 200+ ticks (mean) | 9.1 -> 1.1 | 4.1 -> 1.1 |

**SWARMOS is still slower than the baseline** in 4 of 5 configurations after
this batch. At fleet 8 it previously led by +21 %; it now trails by -6.8 %,
because the shared path fix helped the baseline there more than it helped
SWARMOS. This is reported as measured.

### Powered run (C1 / C2 harness conditions)

Same construction as `tools/verify_criteria_powered.py` (`_make_policy`,
scenario default fleets 40 / 24 / 50, 9000 ticks, seeds 11 13 17 19 23 29 31
37 41), run in parallel, once on the pre-batch HEAD (`a6e1804`) and once on
this batch:

| Scenario | SWARMOS before -> after | Baseline before -> after | Gap before -> after | SWARMOS pair wins |
|---|---|---|---|---|
| blocked_aisle / 40 | 111 -> 365 | 264 -> 465 | -58.0 % -> -21.5 % | 1/9 -> 1/9 |
| narrow_aisle_deadlock / 24 | 56 -> 311 | 126 -> 336 | -55.6 % -> -7.4 % | 0/9 -> 3/9 |
| rush_50 / 50 | 105 -> 394 | 246 -> 399 | -57.3 % -> -1.3 % | 0/9 -> 5/9 |
| **Total (27 pairs)** | **272 -> 1070** | **636 -> 1200** | **-57.2 % -> -10.8 %** | **1/27 -> 9/27** |

- **C1 (zero collisions): MET, both before and after** - 0 collisions in
  both arms across all 27 pairs.
- **C2 (>= 20 % reduction in `avg_completion_s`): still NOT MET.** Before:
  -7.8 %, 95 % CI [-30.9, +15.2]. After: -12.9 %, 95 % CI [-23.1, -2.7].
  The statistic moved the wrong way while throughput rose sharply in both
  arms. That is consistent with its known survivorship bias: an arm that
  completes more tasks also completes more of the tasks that waited longest
  in an oversaturated queue, which raises its average. It is reported as
  measured; redesigning the metric is out of scope for this batch.
- The baseline's large gain (636 -> 1200) comes from the two shared engine
  fixes (4 and 5). The baseline policy was wedging too, just less often.
- Worst compute p95 across all 54 runs: 22.5 ms, against a 100 ms tick budget.

Yields in which the named winner was held by the robot yielding to it:

| Run (1800 ticks) | Before | After |
|---|---|---|
| rush_50 / 50 / seed 13 | 14,779 of 25,681 (58 %) | 4,085 of 17,736 (23 %) |
| narrow_aisle_deadlock / 24 / seed 13 | 7,228 of 10,730 (67 %) | 133 of 1,754 (7.6 %) |
| blocked_aisle / 40 / seed 11 | 9,914 of 17,608 (56 %) | 1,922 of 8,615 (22 %) |

## Not in this batch

Deliberately left for later evaluation: ladder removal or redesign, any
floor-escape exemption, reservation/conflict and auction integration,
communication-fault redesign (blackout and quarantined robots are still
invisible to peers and can still be hit during fault demos), rogue
containment redesign, `LINK_IMPAIR` / `ZONE_PARTITION` wiring, failure-detector
false positives, sovereign-mode gating, and benchmark metric redesign.

## Regression tests

`tests/test_coordination_batch1.py` (23 tests). The behavioural cases were
confirmed to fail on the pre-batch code:

- the reversing-into-the-floor case was granted PROCEED at full speed;
- the mutual-stop case stopped both robots on 5 of 5 ticks;
- the head-on loser returned YIELD instead of REROUTE;
- rush_50 / fleet 8 / seed 11 accumulated 124 inside-floor pair-ticks in
  1500 ticks;
- 61 (SWARMOS) and 11 (baseline) plans started behind the robot in 600 ticks
  of rush_50 / fleet 16.
