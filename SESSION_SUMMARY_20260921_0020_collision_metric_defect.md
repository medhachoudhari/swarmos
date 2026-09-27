# Session summary - 2026-09-21 00:20 - the collision metric was measuring the wrong thing

## Headline

**The collision counts in every arbiter measurement so far are not collision
counts.** They are the number of *ticks* during which at least one overlapping
pair existed. A single pair that freezes inside the 0.70 m threshold and never
separates contributes one "collision" per tick for the rest of the run.

This is a measurement defect in `app/sim/engine.py`, not an arbiter bug, and it
has been silently corrupting the safety signal that every design decision in
this module was being steered by.

## The arithmetic that proves it

`monitor_only`, rush_50, fleet 24, 900 ticks:

| seed | first violation tick | 900 - tick | reported collisions |
|------|---------------------|------------|---------------------|
| 13   | 430                 | **470**    | **470**             |
| 17   | 502 (inferred)      | **398**    | **398**             |

Exact, on both seeds. The diagnostic in `tools/diag_collisions.py` printed a
violation at tick 430, then 431, 432, 433, ... every consecutive tick to the end
of the run. There is no sequence of independent physical collisions that
produces that pattern.

## Why it happens

Three mechanisms compose, and each one is individually defensible:

1. **`observed_states()` (engine.py:330) withholds failed robots.**
   `if not r.failed`. This is deliberate and correct - a dead agent stops
   transmitting, and that silence is the X-23 failure-detector trigger. The
   arbiter is *structurally blind* to failed robots and cannot be blamed for
   hitting one.

2. **`_apply_onboard_brake()` (engine.py:732) is the only defence, and it only
   ever stops the LIVE robot.** `ONBOARD_STOP_M = 0.90`, which is greater than
   `COLLISION_DISTANCE_M = 0.70`, so it does prevent a live robot from driving
   into a failed one. But it has a guard: `if robot.failed or
   robot.speed_scale <= 0.0: continue`. A robot that is **already stopped** is
   skipped, because there is nothing to brake.

3. **`_check_safety()` (engine.py:906) counts state, not events.**
   `if d < COLLISION_DISTANCE_M: self.violations.append(...)` runs every tick
   with no memory of whether this pair was already overlapping last tick.

Put together: a robot fails *while a live peer is already parked within 0.70 m
of it* - which is the normal outcome of a WAIT verdict, and this run issued
**10850** of them with **17 robots held simultaneously**. The pair is now
overlapping and permanently frozen. The live robot is stopped, so the brake
skips it. The failed robot cannot move. The arbiter cannot see the failed robot.
Nothing can ever separate them, and `_check_safety` dutifully re-reports the
same static overlap 470 times.

`failures_confirmed: 2` in the policy stats is the corroborating evidence.

## Why this explains the "stricter kernel, more collisions" paradox

Removing the non-closing exemption made the kernel **strictly more
conservative** - one `continue` that skipped a veto was deleted, so the set of
permitted motions can only have shrunk. A strictly more conservative kernel
cannot cause collisions by permitting motion. That contradiction is what
triggered this investigation, and it was the right thing to chase.

The resolution: the stricter kernel parked **more** robots, for **longer**,
which raised the probability that some robot was sitting inside 0.70 m of a peer
at the instant that peer failed. It did not cause 470 collisions. It caused
roughly one extra frozen pair, which the metric then amplified by a factor of
470.

Note this cuts the other way too, and is the more important lesson:
`ladder_only`'s **2152** "collisions" are also inflated by an unknown factor, so
the ladder is not necessarily as catastrophically unsafe as it looked. Its
+94.7% throughput may be partly real. That has to be re-measured, not assumed.

## What this invalidates

Every collision number in the measurement table in
`SESSION_SUMMARY_20260920_2238_m4_arbiter_wip.md` is suspect, in both
directions. Specifically:

- The "0 collisions" results are still **trustworthy**. Zero ticks with an
  overlap does mean zero overlaps. A false zero is not possible here.
- Every **non-zero** result is an unknown overcount and must be re-measured
  before it is used to reject a design.
- The judgement that version 7 of the exemption was unsound (600-916) and that
  version 8 was still unsound (1, 3) used this metric. The version 7 verdict is
  probably still right - a genuine fail-open on crossing traffic was identified
  by *reading* the geometry, independently of the counts. But the version 8
  verdict rested on "1 and 3 collisions", and 1 tick of overlap may be a single
  transient pair, not 3 separate crashes. **Deleting the exemption may have been
  the wrong call**, and it is now cheap to re-test once the metric is fixed.

## The fix, in priority order

1. **Count collision EVENTS, not overlapping ticks.** Track the set of
   overlapping pairs and only append a `Violation` on the tick a pair *enters*
   the overlap state. Keep a separate `overlap_ticks` counter for dwell, because
   how long an overlap persists is genuinely interesting and should be visible -
   just not as the headline safety number. This is the honest metric and it is
   what the success criterion "zero collisions" was always meant to express.
2. **Re-run `tools/diag_isolate.py`** and rebuild the entire measurement table
   against the corrected metric before making any further design decision.
3. **Re-test the version 8 gated exemption** against the corrected metric. It
   may well have been sound, and it is the mechanism that lets wedged pairs
   separate, which is exactly what this run is starving for.
4. **Then** attack the real throughput problem, which this investigation has
   made unmistakable: 10850 WAIT verdicts, 11201 monitor vetoes, 12.4 vetoes per
   tick, 17 of 24 robots held at once, 3 tasks completed. The kernel is not
   unsafe, it is **paralysed**. That is the actual gap to the +20% target.
5. Separately, consider whether a stopped robot should still be checked by the
   onboard brake when a peer fails next to it. Physically a real AMR that finds
   itself within 0.70 m of a newly dead machine would back off, not sit there
   forever. That is a simulation-fidelity question, lower priority than the
   metric.

## Process note

Two things found this bug, and both are worth keeping:

- **The isolation harness with a no-kernel control.** It has now caught three
  distinct defects: a bad splice (full == ladder_only byte-for-byte), the
  missing deadlock breaker (monitor_only == baseline byte-for-byte), and now
  this.
- **Refusing to accept a contradiction.** "A stricter kernel produced more
  collisions" is impossible. The temptation was to patch the arbiter again; the
  correct move was to stop and demand the raw violation records. Four legs of
  this module were spent tuning an arbiter against a metric that was lying.
  Instrument first, tune second.

## Status of the six modules

Unchanged by this leg. M5 sim (32 tests), M6 db (26 tests), M4 core (296 tests)
green; the arbiter `SwarmPolicy` still has no tests of its own, which remains
the largest outstanding risk in the module and would plausibly have caught the
frozen-pair case as a unit test.
