# Fleet gridlock on rush_50 at fleet 50 - root cause and fix

Date: 2026-09-22 (root-caused), updated 2026-09-22 (fixed)
Status: **fixed and regression-tested**
Reported from: operator console, rush_50 / seed 18 / fleet 50 / integrity on,
showing `WAITING 29`, `TASKS PER MINUTE 1.73`, `REPLANS 3,324`, `COLLISIONS 0`.

This is the defect `docs/ROBONEX_SWARMOS_UI_TRANSFORMATION_CHECKPOINT.md`
section 12 called "the next task". It has now been measured, root-caused,
fixed, and covered by a regression test
(`tests/test_sim_engine.py::test_no_robot_stalls_forever_at_high_density`).

---

## 1. Is it expected?

**No.** It is a real defect: a permanent, unbounded wedge, not saturation.

A fleet sweep on its own looks like congestion collapse (throughput falls
from fleet 16 to fleet 50), and that reading is not wrong at the aggregate
level - real density congestion is present and is not being claimed to be
fixed here. What was wrong, and is now fixed, is a SPECIFIC additional
failure: individual robot-pairs at high density could land inside each
other's safety floor and never recover, holding their tasks and retiring
fleet capacity permanently for the rest of the run.

---

## 2. Root cause (revised from the original write-up)

The first version of this document theorised that `_plan()` sometimes left a
robot with `current_task_id` set and `path == []` forever, because nothing
re-consumed a REROUTE verdict for a robot that already held a task. That
theory was tested directly with instrumented sweeps
(`tools/diag_wedge_reason.py`, `tools/diag_wedge_census.py`,
`tools/diag_frozen_robot.py`) and **falsified**: `_plan()` is called every
tick, `_apply_verdicts` always clears the path on `needs_replan`, and a
cleared path is always handed a fresh route by the very next `_plan()` call.
No robot was ever observed with a path-less task for more than a handful of
ticks - the "empty path forever" state does not occur.

What actually happens, confirmed by tracking one robot tick-by-tick
(`R001`, tick 4000-4400, fleet 50, seed 18):

    tick=4001 R001 WAIT   safety monitor veto: swept path within 0.56 m of R029
    tick=4003 R001 REROUTE safety monitor held 4 ticks behind R029, replanning
    tick=4006 R001 YIELD  yielding to R029, utility margin 0.301
    tick=4007 R001 YIELD  committed for 7 more ticks
    tick=4014 R001 WAIT   safety monitor veto ... R029  (again)
    tick=4015 R001 REROUTE safety monitor held 4 ticks behind R029, replanning
    ... repeats indefinitely, position frozen at (52.50, 29.11) the entire time

R001 is issued a *fresh path* every time REROUTE fires (`replans` climbs into
the tens of thousands over the run), and it never leaves `(52.50, 29.11)`.
This is exactly what the safety monitor's own docstring in
`swarm_policy.py._monitor` documents as a **known limitation**:

    KNOWN LIMITATION, measured and documented rather than fixed.
    swept(scale) always contains `here`, so the gap above is
    bounded by the standing-still gap for EVERY scale. Once a pair
    is inside the floor no fraction of the step clears it, so the
    graded MONITOR_SCALES fallback cannot fire and the clamp ratio
    stays at 0.038 to 0.270 - almost every intervention is still a
    full stop.

Once R001 and R029 are mutually inside `HARD_STOP_M`, no speed scale the
monitor can grant clears the floor, so every tick is a full stop; after
`MONITOR_STUCK_TICKS` (4) it fires REROUTE; the new path leads straight back
into the same standing peer; and the cycle repeats. Five earlier versions of
the monitor's geometry were tried and rejected (see the monitor's own
docstring) because loosening it re-introduced collisions - this is a
deliberate, measured trade-off, not an oversight.

The consequence, confirmed with a wedge census across a 9000-tick run: task
completions freeze at a small number (5-10) from roughly tick 3000 onward
while `tasks_pending` grows unbounded, even though no single robot has a
literally empty path for more than a few ticks at a time. The wedge is real;
it is just a symmetric standoff, not an empty-path bug.

---

## 3. The fix

Changing the safety-kernel geometry was tried five times by the original
authors and rejected every time for costing collisions (see
`swarm_policy.py._monitor`'s docstring). This fix does not touch that
geometry. Instead, in `app/sim/engine.py`:

* **`STALL_EPS_M` / `STALL_RELEASE_TICKS`** (new constants): a robot holding
  a task is tracked tick-by-tick; if it has not moved at least 2 cm in
  150 ticks (15 s), the task is released back to the pending pool (the same
  "release, don't loop forever" recovery `StopAndWaitPolicy` already uses),
  and the robot returns to `AVAILABLE`.
* **`SimEngine._check_stalls()`** (new method, called once per tick after
  `_service()`): implements the tracking and release. Dwelling at a pick/drop
  station resets the clock, so legitimate rest is never mistaken for a stall.
  Quarantined, failed, or task-less robots are never tracked.
* This is a bookkeeping-only change: it never moves a robot and never
  overrides a Verdict. It only decides how long a robot may keep re-trying a
  standoff the safety kernel and the ladder cannot themselves resolve.

Verified with an instrumented 6000-tick run (fleet 50, seed 18): the worst
observed stall streak across every robot was exactly 150 ticks (the bound),
never higher, with 1598 releases fired and 0 collisions. This is also now a
permanent regression test:

    tests/test_sim_engine.py::test_no_robot_stalls_forever_at_high_density

---

## 4. What changes and what does not

* **Fixed:** no robot can be held with zero net progress for longer than
  `STALL_RELEASE_TICKS` (150 ticks / 15 s). The permanent, unbounded wedge is
  eliminated - proven, not assumed, by direct measurement over 6000 ticks.
  `COLLISIONS 0` is unaffected: 0 both before and after.
* **Not claimed to be fixed:** aggregate throughput at very high density
  (fleet 40-50) is still low, because the underlying cause of the WAIT/YIELD
  churn is genuine spatial congestion in a fixed-size warehouse, which this
  fix does not and should not try to solve by changing the safety kernel.
  Fleet 16 remains the measured throughput optimum on this floor plan.
  `REPLANS` will still read high at high density, because REROUTE genuinely
  does replan every time it fires - it is just no longer able to trap a
  robot forever.

---

## 5. Workaround for a demo (still valid, now belt-and-suspenders)

* Fleet 8 (the `run.sh` default) remains the cleanest demo point.
* Fleet 16 remains the measured throughput optimum if a busier floor is
  wanted on screen.
* Fleet 40-50 will still show low throughput on a short run because of
  genuine congestion, but will no longer show the "stuck forever" pattern -
  robots visibly resume once their `stall_releases` fires, which is itself a
  legitimate resilience story: "the fleet detects it cannot win a
  standoff and reassigns the work instead of stalling forever."

---

## 6. Reproduce

    cd /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920

    # confirms completions no longer freeze after ~tick 3000 the way they did
    PYTHONPATH=. python3 tools/diag_runlength_probe.py

    # confirms no stall streak ever exceeds STALL_RELEASE_TICKS
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest \
        tests/test_sim_engine.py::test_no_robot_stalls_forever_at_high_density -v

Both probes must build the engine with the real policy factory:

    SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

`SimEngine(scen, seed=SEED)` defaults to `policy=None`, which runs with no
coordination at all and measures nothing. `ScenarioSpec` is a frozen
dataclass: a fleet override must rebuild it,
`type(base)(**{**base.__dict__, "fleet_size": n})`, not assign to it.
