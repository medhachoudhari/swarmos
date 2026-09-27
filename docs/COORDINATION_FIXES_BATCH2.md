# Coordination, resilience and fault correctness - batch 2

Date: 2026-09-26. Status: implemented locally on top of batch 1 (`836aa15`),
not pushed. Remote branch still at `a6e1804`.

Batch 2 targets the remaining yield/wait deadlock and the fault-handling
defects found by the diagnostic: false sovereign triggers, false failure
confirmations, link impairment and zone partition that did nothing, and
quarantined or silent robots that were invisible to the safety monitor.

Nothing here changes the baseline policy, the 0.75 m floor, seeds, task
streams, fleet sizes, durations, WIP, dwell/service parameters or the
collision definition. The ML layer is untouched.

**Fairness check, measured:** the baseline arm's trace hash is bit-identical
between batch 1 and batch 2 in all 43 evaluation runs, including every fault
run. The shared-code changes in this batch (radio, engine fault wiring,
telemetry) do not alter the baseline's behaviour at all.

## A. Files changed

| File | Scope | Change |
|---|---|---|
| `app/coordination/swarm_policy.py` | SWARMOS only | Phases 1, 2, 3 (policy side), 5, and 6 counters |
| `app/coordination/radio.py` | Shared radio; the baseline has no radio | Zone partition in `BoundedRadio`; `FailureDetector.evaluate(hold=, revive=)` |
| `app/sim/engine.py` | Shared engine | Phase 4 fault wiring; Phase 6 telemetry (replans, stalled robots, coordination block) |
| `tests/test_coordination_batch2.py` | Tests | 30 new regression tests |
| `docs/COORDINATION_FIXES_BATCH2.md` | Docs | This file |

## B. Exact fixes

### Phase 1 - yield/wait deadlock (SWARMOS only)

- **Third-party feasibility.** Batch 1 swapped right of way only when the
  utility winner was blocked by the loser itself. A winner boxed in by a
  third robot that is standing still (declared hold, or nowhere to go) now
  counts as unable to pass, and the free robot gets right of way.
  `SwarmPolicy._blocked_by_standing`. Moving third parties are ignored, so a
  convoy is never mistaken for a blockage.
- **Stuck-winner detection.** A loser counts consecutive contest ticks in
  which its winner has broadcast `holding` (it did not move). Reaching
  `STUCK_YIELD_TICKS` is counted (`stuck_yield_detections`).
- **Stuck-winner response: measured, rejected as a default.** Three responses
  were implemented and measured over 25 paired runs (SWARMOS tasks):

  | Response | Tasks |
  |---|---|
  | none (keep yielding) | **278** |
  | replan around the winner, 3-tick trigger | 250 |
  | replan around the winner, 10-tick trigger | 255 |
  | stop yielding and propose motion | 251 |

  Every active response lowered throughput; the replan cost the narrow aisle
  37 -> 29. Each replan zeroes the robot's velocity, and most "stuck" winners
  resume within a few ticks. The replan is kept as an opt-in flag
  (`STUCK_YIELD_REPLAN = False`) so the result is reproducible. The batch-1
  head-on replan and `YIELD_PATIENCE` still apply.
- **Repeated-contest telemetry.** `repeated_contests` counts re-contests of
  the same pair within 50 ticks.

### Phase 2 - sovereign mode (SWARMOS only)

The old trigger was "hear no peer for 5 ticks", which also fires for a robot
simply more than 15 m from everyone. The new trigger requires **evidence**:
the robot's onboard perception (the ground-truth sightings the engine already
passes to `observe()`, within 12 m) sees at least one peer it ought to hear -
one not confirmed dead and not deliberately quarantined - yet it hears none.

| Case | Behaviour |
|---|---|
| A. Geographic isolation | Nobody in sight, so no evidence and no sovereign |
| B. Mild packet loss | Some peers still heard, so no sovereign |
| C. Total link impairment | Peers in sight, none heard: sovereign; rejoins when the link returns |
| D. Blackout | Sovereign; rejoins when the radio is restored |
| E. Sustained radio failure | Stays sovereign and keeps working; rejoins afterwards |

With no evidence either way the state is held, not reset. A radio-quarantined
(contained) robot is never sovereign: its silence is containment, not a link
fault. The speed cap and wider floor are unchanged. Without perception input
(policy driven directly), the original rule applies.

### Phase 3 - failure detector (policy side SWARMOS only; detector API shared)

`FailureDetector.evaluate` takes two optional sets; both default to empty,
which gives the old behaviour.

- **`hold`**: peers that may be SUSPECTED but never newly confirmed FAILED:
  - peers that no credible witness can see - a witness must be receiving
    messages itself, have its radio up, and be within range and not across a
    partition;
  - peers the fleet has quarantined.
- **`revive`**: peers seen moving. A robot seen moving is alive, so even a
  confirmed failure drops back to SUSPECTED.

A genuinely failed robot stops in view of its neighbours and is still
confirmed within a few ticks.

### Phase 4 - LINK_IMPAIR / ZONE_PARTITION (shared engine and radio)

Before: both faults only wrote `engine.impairment`; the radio never changed.

After:

- **`LINK_IMPAIR`** calls `BoundedRadio.set_profile` with the requested loss
  and latency. Latency is rounded to whole 100 ms ticks; jitter is recorded
  but not modelled.
- **`ZONE_PARTITION`** cuts every radio link that crosses the zone boundary.
  Zone membership is refreshed every tick before arbitration.
- **Duration.** Both expire after 300 ticks by default (`ticks=`), mirroring
  `COMM_BLACKOUT`, and emit `impairment_ended`.
- **Determinism.** Loss draws use the policy's seeded RNG, so impaired runs
  replay bit-identically.
- **Baseline.** It has no radio, so both faults return `applied: false`
  there, exactly as `COMM_BLACKOUT` already did.

### Phase 5 - quarantined and silent robots stay physical (SWARMOS only)

The safety monitor now adds **perception obstacles**. It takes every robot in
this robot's sightings that is either missing from its fresh radio inbox
(silenced, impaired, partitioned, quarantined, failed) or whose radio claim
contradicts the sighting by more than the integrity layer's
`CLAIM_TOLERANCE_M` (a liar). Each becomes a standing obstacle at its true
position, cleared by `floor + MAX_STEP_M`, which bounds any move that robot
can make this tick.

With clean links and no faults every sighted peer is in the inbox and
consistent, so this adds nothing in normal operation. Quorum-based rogue
detection and containment are unchanged.

### Phase 6 - telemetry (shared engine counters; not part of the trace hash)

- **`replans`.** It used to be incremented when a path was cleared *and again*
  when the next path was planned, and it also counted every first plan for a
  new goal. Now each plan is counted once:

  | Counter | Meaning |
  |---|---|
  | `path_plans` | Every path handed to a robot |
  | `initial_plans` | Plans for a new goal |
  | `replans` | Plans that replace an invalidated path |
  | `path_invalidations` | Paths cleared by a verdict or an invalidation |

- **`robots_stalled`** (new KPI): robots holding a task with no measurable
  progress for 5 s or more, excluding pick/drop dwell.
- **`coordination`** (new KPI block): the arbiter's contest, yield,
  winner-held, stuck-yield, swap, head-on, monitor, perception and failure
  counters. It is empty for the baseline.
- **Sovereign and failure counts** now describe real events (see J, K).
- **YIELD / WAIT / REROUTE, task completion:** verified consistent; no change
  needed.

None of these counters is hashed, so the telemetry fix changes no behaviour.
Historical logs and docs are untouched.

## C. Tests

| | Batch 1 | Batch 2 |
|---|---|---|
| pytest | 599 passed | **629 passed** (599 + 30 new) |

## D. UI verifier

34 pass / 1 warn / 0 FAIL, unchanged. The warning is the long-standing
"ids reached through computed selectors" one. A live server plus headless
browser check shows link Live, ticks advancing and no console errors, and
`link_impair`, `zone_partition`, `comm_blackout` and `rogue_agent` all inject
with `applied: true`.

## E. Deterministic replay

Re-running four configurations (including LINK_IMPAIR and ROGUE_ROBOT with
integrity) reproduced both arms' trace hashes bit for bit. Dedicated tests
cover impaired runs and both arms.

## Measurement setup

- **Normal runs:** 25 paired runs, identical to the batch-1 benchmark (rush_50
  fleets 8 / 16 / 50, narrow_aisle_deadlock 24, blocked_aisle 40; seeds 11 13
  17 19 23; 1800 ticks each).
- **Fault runs:** 18, all on rush_50 fleet 16, fault injected at tick 300,
  1200 ticks, seeds 11 13 17.
- **Both arms** are built exactly as `app/sim/cosim.py` builds them.
- **"Before"** is the batch-1 commit `836aa15`, measured with the same harness.

## F. Collisions

| | Batch 1 | Batch 2 |
|---|---|---|
| 25 normal runs, SWARMOS / baseline | 0 / 0 | 0 / 0 |
| Powered 27 pairs x 9000 ticks, SWARMOS / baseline | 0 / 0 | 0 / 0 |
| Fault: COMM_BLACKOUT (3 runs) | 3 | **0** |
| Fault: ROGUE_ROBOT + integrity (3 runs) | 12 | **0** |
| Fault: ROGUE_ROBOT, integrity off (3 runs) | 14 | 6 |
| Fault: ROBOT_FAILURE / LINK_IMPAIR / ZONE_PARTITION | 0 / 0 / 0 | 0 / 0 / 0 |

Rogue with integrity **off** still collides (baseline: 7). With no containment
the rogue keeps driving on its own lie; peers now see its true body and stop,
but a moving adversary can still strike a stationary robot. Integrity off is
the defenceless configuration by design. This is pre-existing and remains open.

## G. Inside-0.75 m pair-ticks

| | Batch 1 | Batch 2 |
|---|---|---|
| SWARMOS, 25 normal runs | 0 | 0 |
| Blackout runs | 53 | 0 |
| Rogue + integrity runs | 202 | 0 |

## H. Winner-not-moving

Share of YIELDs whose named winner was granted no motion that tick:

| Config | Batch 1 | Batch 2 |
|---|---|---|
| rush_50 / 8 | 22.8 % | 30.3 % |
| rush_50 / 16 | 30.5 % | 25.6 % |
| rush_50 / 50 | 46.8 % | 36.9 % |
| narrow / 24 | 32.5 % | 36.5 % |
| blocked / 40 | 45.0 % | 38.6 % |
| **All 25** | **42.8 %** | **36.0 %** |

Better at high density, worse at fleet 8 and in the narrow aisle.

## I. YIELD / WAIT / REROUTE / repeated contests (25 runs, SWARMOS)

| | Batch 1 | Batch 2 |
|---|---|---|
| YIELD | 177,785 | 169,273 |
| WAIT | 61,219 | 73,060 |
| REROUTE | 34,637 | 38,651 |
| YIELD-WAIT-YIELD / WAIT-YIELD-WAIT oscillation windows | 1,680 | **620** |
| Yield episodes that repeat a pair within 50 ticks | 87.5 % | 87.2 % |

WAIT rose: more robots now propose motion that the monitor then holds, instead
of yielding up front. Repeated pair contests are essentially unchanged; this
batch did not solve them.

## J. Sovereign false triggers

| | Batch 1 | Batch 2 |
|---|---|---|
| Sovereign entries, 25 normal runs (all false: no comm fault) | 172 | **0** |
| Sovereign robot-ticks, 25 normal runs | 24,177 | **0** |
| ROBOT_FAILURE runs (no comm fault) | 2,998 ticks | 0 |
| LINK_IMPAIR default 10 % loss | 2,421 ticks | 0 (mild loss, by design) |
| ZONE_PARTITION | 2,421 ticks | 161 (genuine partition) |
| COMM_BLACKOUT | 2,973 ticks | 162 |

Recovery is verified by tests for total impairment, blackout and sustained
radio failure: each robot rejoins once it hears a peer again.

## K. Failure detector

| | Batch 1 | Batch 2 |
|---|---|---|
| FAILED confirmations of robots that had not failed, 25 normal runs | 161 | **0** |
| Same, fault runs (failure / blackout / impair / partition / rogue+i / rogue) | 25 / 18 / 17 / 17 / 16 / 17 | 0 / **2** / 0 / 0 / 0 / 0 |

The 2 remaining are a blacked-out robot confirmed while it stood still in
view of its neighbours. It is revived as soon as it is seen moving. From
perception plus silence, a stationary silent robot is indistinguishable from a
dead one; treating it as dead is the conservative error. Genuine failures are
still confirmed (test).

## L. Communication faults

- **LINK_IMPAIR** now drops and delays messages. A test shows
  `radio.stats.dropped` rising and the profile restoring after expiry.
- **ZONE_PARTITION** now cuts cross-boundary links only. A test shows
  membership populated and cleared after expiry.
- **Neither affects the baseline**, which has no radio.
- **The default LINK_IMPAIR request is mild.** It asks for 10 % loss and
  40 ms latency, and 40 ms rounds to 0 ticks at 10 Hz. Its measurable effect
  in the fault runs is therefore small, which is the honest consequence of the
  requested values.

## M. Rogue quarantine

- **Containment still works.** Quorum containment fired in all 3 integrity
  runs, just as in batch 1.
- **No more collisions.** In batch 1 a contained rogue was hit 12 times across
  those runs; in batch 2, 0.
- **Telemetry fixed.** A contained robot is no longer counted as sovereign or
  as failed.
- **Rehabilitation (release after clean behaviour) is not exercised.** A rogue
  in this simulation never stops lying, so there is nothing to observe.

## N. Task completion, SWARMOS vs baseline

25 normal runs (1800 ticks):

| Config | SWARMOS B1 -> B2 | Baseline B1 -> B2 | Gap B1 -> B2 |
|---|---|---|---|
| rush_50 / 8 | 41 -> 40 | 44 -> 44 | -6.8 % -> -9.1 % |
| rush_50 / 16 | 47 -> 51 | 65 -> 65 | -27.7 % -> -21.5 % |
| rush_50 / 50 | 67 -> **84** | 83 -> 83 | -19.3 % -> **+1.2 %** |
| narrow / 24 | 38 -> 37 | 49 -> 49 | -22.4 % -> -24.5 % |
| blocked / 40 | 67 -> 66 | 97 -> 97 | -30.9 % -> -32.0 % |
| **All 25** | **260 -> 278** | **338 -> 338** | **-23.1 % -> -17.8 %** |

Powered run (27 pairs, 9000 ticks, scenario default fleets):

| Scenario | Pre-batch-1 | Batch 1 | Batch 2 | Baseline (B1 and B2) |
|---|---|---|---|---|
| blocked_aisle / 40 | 111 | 365 | 352 | 465 |
| narrow_aisle_deadlock / 24 | 56 | 311 | 318 | 336 |
| rush_50 / 50 | 105 | 394 | **405** | 399 |
| **Total** | **272** | **1070** | **1075** | **1200** |
| Gap | -57.2 % | -10.8 % | **-10.4 %** | |
| SWARMOS pair wins | 1/27 | 9/27 | 9/27 | |
| C2 (`avg_completion_s` reduction, target +20 %) | -7.8 % | -12.9 % | -10.8 %, CI [-20.7, -0.9] | |

The pre-batch-1 baseline total was 636.

## O. Performance gap

- **Short horizon** (25 runs, 1800 ticks): -23.1 % -> **-17.8 %**.
- **Long horizon** (27 powered pairs, 9000 ticks): -10.8 % -> **-10.4 %**,
  which is within noise. **Batch 2 did not measurably move long-run
  throughput.** Its gains are in correctness and fault safety, plus a
  short-horizon gain concentrated at fleet 50.
- **C2 is still NOT MET.**

## P. Regressions

- **Winner-not-moving rose** at fleet 8 (22.8 -> 30.3 %) and in the narrow
  aisle (32.5 -> 36.5 %).
- **Throughput is flat or slightly lower** in the narrow aisle (38 -> 37),
  blocked aisle (67 -> 66) and fleet 8 (41 -> 40) over 5 seeds. These are
  within single-seed noise, but not improvements.
- **Blocked aisle (powered):** 365 -> 352.
- **SWARMOS WAIT count rose 19 %**, and stall releases rose 823 -> 863.
- **Blackout runs:** 2 stationary-silent robots are still confirmed FAILED
  (conservative, and revived when they move).
- **The stuck-winner replan was built and measured as a regression**, so it
  ships disabled.

## Q. Remaining bottlenecks

1. **Repeated pair contests.** About 87 % of yield episodes repeat the same
   pair within 50 ticks. Every attempt to break them by force (replan, take
   the gap) cost more than it saved. The ladder's contest band (0.97 m) is the
   likely lever, and ladder redesign was out of scope.
2. **Blocked-aisle and narrow-aisle throughput** trail the baseline by 5-25 %
   at every horizon.
3. **Density congestion at stations** is shared by both arms.
4. **Rogue robot with integrity off** still causes collisions in both arms.
5. **C2 metric bias.** `avg_completion_s` is survivorship-biased in an
   oversaturated queue. Redesigning the metric was out of scope.

## Batch separation

| | Batch 1 (`836aa15`) | Batch 2 (this) | Still pre-existing |
|---|---|---|---|
| Floor entries / wedges | Fixed (84,299 -> 0) | - | - |
| Mutual-stop contests | Fixed (pairwise) | Extended to third parties | Repeated pair contests |
| Backward replans, stall re-dispatch | Fixed (shared) | - | - |
| False sovereign | - | Fixed | - |
| False failures | - | Fixed (2 conservative in blackout) | - |
| LINK_IMPAIR / ZONE_PARTITION | - | Wired | Jitter not modelled |
| Quarantine / blackout invisibility | - | Fixed (0 collisions) | Rogue with integrity off |
| Telemetry | - | Fixed | - |
| C2 | Not met | Not met | Metric bias |
