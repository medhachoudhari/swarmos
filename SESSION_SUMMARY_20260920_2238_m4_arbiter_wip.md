# Session checkpoint - 2026-09-20 22:38 - M4 arbiter, work in progress

## Status: full suite GREEN at 380 tests. SwarmPolicy exists but LOSES to the baseline.

Honest statement of where this stands: the arbiter is written, it is safe, and it
is measurably WORSE than stop-and-wait on throughput. It is not demo-ready and
the >=20% claim is not yet met. Do not present it. The diagnosis below is the
real output of this leg.

## Completed and verified this leg

1. `MessageType.HEARTBEAT` added to `app/coordination/messages.py`. The enum
   docstring had already reserved it. No schema change.
2. `tests/test_radio.py` - 26 tests, all passing.
3. Radio surface exported from `app/coordination/__init__.py` (BoundedRadio,
   LinkProfile, LINK_PERFECT/DEGRADED/SEVERE, FailureDetector, FailureEvent,
   PeerHealth, RadioStats, R_COMM_M, HEARTBEAT_*, CONFIRM_TIMEOUT_S).
4. Full suite: **380 passed in 17.69s** (was 354).
5. `app/coordination/swarm_policy.py` written - X-25 bounded radio, X-09 Simplex
   monitor, X-18 graded ladder, X-24 deterministic contest, `explain()` for X-26.
6. `tools/smoke_swarm.py` - fast 3-seed A/B harness. NOT evidence; the real
   evidence path is `app/db/benchmark.run_ab` over >=10 seeds with a paired CI.

## The measurements, in order, with what each one taught

Scenario: rush_50 with fleet_size=24, 900 ticks, seeds 11/13/17.
Baseline completions: 7 / 4 / 8. Control (NoOpPolicy): 600 collisions, which
confirms the collision counter is a real measurement and not a hardcoded zero.

| attempt | change | swarmos completions | verdict |
|---|---|---|---|
| 1 | first write | 2 / 0 / 5 | -71% / -100% / -37% |
| 2 | CAUTION 1.60 -> 1.25, CONFLICT 1.00 -> 0.95, peers broadcast `holding` | 1 / 0 / 5 | no better |
| 3 | contest winner PROCEED at full speed instead of SLOW 0.6 | 1 / 0 / 5 | no better |

Collisions stayed at 0 in every SWARMOS run, so safety is not the problem.

### What the numbers actually say

Per run of ~21600 robot-ticks, seed 11 attempt 3:
PROCEED 7652, SLOW 656, WAIT 7536, YIELD 5756. Contests 12436. Vetoes 7536.

Two facts dominate:

1. **The monitor vetoes ~35% of all robot-ticks** and every veto is a full
   WAIT. `monitor_vetoes == WAIT count` exactly, which means every single WAIT
   in the run came from the monitor, not from the ladder. The ladder is being
   bypassed.

2. **YIELD + WAIT is ~61% of all robot-ticks.** The fleet is stopped most of
   the time. Near-misses went UP (3057 -> 8589) while completions went DOWN,
   which is the signature of robots crowding into each other's caution bands
   and then mutually freezing rather than flowing.

### Diagnosis - three distinct causes, ranked

**Cause A (largest): the monitor is symmetric, so it recreates the exact
failure the baseline docstring warns about.** `app/sim/policy.py`
StopAndWaitPolicy's docstring explains at length that a symmetric rule wedges
head-on traffic permanently, and that the fix is right of way via a total
order. The baseline HAS that fix. My monitor does not: it evaluates each robot
independently against every peer's projected step, so in a head-on pair both
robots veto themselves. `holding` was supposed to break this, but it only helps
on the tick AFTER someone has already yielded, and the monitor fires before the
ladder's decision has propagated.

Fix to try: give the monitor the same right-of-way asymmetry the baseline has.
A robot should only veto itself against a peer that has priority over it under
the SAME total order used by the contest (utility, then id). Against a
lower-priority peer it proceeds and lets that peer stop. Safety is preserved
because exactly one of the pair still stops, which is all separation requires.
This is the single change most likely to flip the result.

**Cause B: the ladder's SLOW band is nearly dead.** SLOW is only 656 of 21600
robot-ticks, but SLOW-instead-of-halt was supposed to be the main source of the
throughput gain. Because CAUTION_M was cut to 1.25 and CONFLICT_M is 0.95, the
SLOW window is a 0.30 m shell that robots cross in under two ticks. Widen the
gap between the two thresholds so SLOW is a band the fleet actually occupies.

**Cause C: `speed_scale` may not be doing what I assume.** I have NOT verified
how `app/sim/engine.py` consumes `verdict.speed_scale` - whether a SLOW verdict
genuinely produces a partial step, and whether YIELD vs WAIT differ at all in
the engine's motion update. Check this BEFORE tuning further. If the engine
treats any non-1.0 scale as a stop, every number above is explained trivially
and the ladder was never actually being exercised.

## Attempt 4 - Cause C cleared, Cause A fixed, STILL LOSING

**Cause C is disproved.** `app/sim/engine.py` does
`robot.apply_verdict_scale(verdict.speed_scale or 0.0)`, which is genuinely
proportional. The ladder was always being applied correctly. Rule this out.

**Cause A's fix was applied** - `_monitor` is now asymmetric on ascending id
(hold against a higher-id peer; against a lower-id peer judge only against
where that peer stands). Result: 1 / 0 / 5 completions. **No improvement.**

So the symmetric-monitor theory, while a real defect worth fixing, was NOT the
dominant cause. The remaining evidence points somewhere else.

### The finding that actually matters: this is OSCILLATION, not deadlock

Look at seed 11 attempt 4: contests 12669 against ~21600 robot-ticks, so
**~59% of all robot-ticks reach a contest**, meaning the fleet is essentially
permanently inside CONFLICT_M. And critically:

**`reroutes = 0` on seeds 11 and 13, with YIELD_PATIENCE = 25.**

That is the smoking gun. If robots were deadlocked, streaks would reach 25 and
fire thousands of reroutes. Zero reroutes means **no robot ever yields 25 ticks
in a row** - the streak keeps resetting. The fleet is not wedged; it is
CHATTERING. Each robot yields, immediately wins the next tick, yields again,
and so makes almost no net forward progress while never triggering the
anti-starvation recovery.

Two mechanisms in the current code produce exactly this, and both need fixing:

1. `self._yield_streak.pop(rid, None)` is called on every PROCEED and on every
   contest win. So a single winning tick erases the entire waiting history.
   The aging term then never grows, so the contest outcome is decided purely by
   progress/momentum/battery, which flip-flop tick to tick.
2. A contest winner is not committed to anything. Next tick it re-contests from
   scratch against possibly a different `worst_encounter` peer. There is no
   hysteresis and no notion of holding a won right of way for the few ticks it
   takes to actually clear the intersection.

### Recommended fix for the next leg - hysteresis and commitment

- Do NOT reset `yield_streak` on a win. Decay it (e.g. `streak = max(0, streak
  - 1)`) so waiting history persists and aging can actually accumulate.
- Add a short **commitment window**: when a robot wins a contest against a
  peer, record `(peer, tick)` and keep granting itself right of way over that
  same peer for the next N ticks (N ~ 5-8, roughly the time to cross a 1 m
  aisle) without re-running the contest. Both sides compute the same thing, so
  the loser also stays committed to yielding. This is the standard cure for
  arbitration chatter and it is what turns a won contest into actual progress.
- Reconsider CAUTION_M / CONFLICT_M only AFTER the above. With ~59% of
  robot-ticks in contest, the bands are clearly still too wide for a 24-robot
  fleet in this warehouse, but widening/narrowing them will not fix chatter.

## Next step - do these in this order

1. Implement the two hysteresis fixes above (persistent yield_streak + a
   commitment window). This is the highest-value change remaining.
2. Re-run `tools/smoke_swarm.py`. Watch `reroutes` - it should become non-zero
   if genuine standoffs exist, and contests should drop well below 59%.
3. If still losing, reduce CAUTION_M toward 1.0 and re-measure.
4. Target: beat the baseline at all 3 seeds with 0 collisions. Only then move
   to the 10-seed `run_ab` evidence run.
5. Write `tests/test_swarm_policy.py` - the arbiter currently has NO tests.

   Must cover: bounded radio means no global view, determinism (same seed ->
   same verdicts), monitor veto is final, contest is symmetric across both
   parties, yield patience triggers reroute, failed peer causes reroute not
   wait, no starvation (aging eventually wins).
6. Then M2 `app/api/`, M1 `web/`, M3 `app/ml/`, evidence, run.sh, README, deck.

## Fallback if the arbiter cannot be made to win

If after Cause A and B it still loses, the honest move is to keep the baseline
as the shipped coordinator and present SWARMOS's genuine differentiators, which
do NOT depend on the throughput claim: N3 deterministic replay, N5 the runtime
assurance monitor, N9 adversarial containment, N10 counterfactual co-simulation,
plus the bounded-radio O(k) message scaling. Claiming 20% without the paired CI
to back it would be the one thing that loses this hackathon outright.

## Environment reminders

- Python: `/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3`
- Tests: `cd <repo> && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. <python> -m pytest tests/ -q`
- KPI keys are `tasks_complete`, `tasks_per_min`, `avg_completion_s`,
  `collisions`, `near_misses`, and `compute.p95_ms` - NOT `tasks_completed` or
  `tick_p95_ms`. That mistake made the first smoke run print all zeros.
- Every file written gets an auto-appended AI-generated-content footer. Expected.
