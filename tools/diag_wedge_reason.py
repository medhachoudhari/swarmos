#!/usr/bin/env python3
"""Find one wedged robot (current_task_id set, path empty) and print exactly
which branch of SimEngine._plan() is skipping it, tick by tick, for a short
window. This settles the open question in docs/GRIDLOCK_DEFECT_20260922.md:
does _plan() actually run for these robots and fail, or does something else
prevent _plan() from being reached at all.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import RUSH_50

SEED = 18
FLEET = 50
TICKS = 9000


scen = type(RUSH_50)(**{**RUSH_50.__dict__, "fleet_size": FLEET})
eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

# A robot with an empty path during its DWELL_TICKS pause after pick/drop is
# expected, not wedged - it recovers on its own once dwell hits 0. Only count
# it as a candidate wedge if it still has no path AFTER dwell has cleared, and
# require that state to persist for several ticks before treating it as real.
wedge_rid = None
wedge_tick = None

for t in range(TICKS):
    eng.step()
    if eng.tick < 300:
        continue  # let the fleet ramp up before looking for the pattern
    for rid, r in eng.robots.items():
        no_path_task = (
            r.current_task_id is not None
            and not r.path
            and not r.failed
            and not r.quarantined
            and eng._dwell.get(rid, 0) == 0
        )
        if no_path_task:
            wedge_rid = rid
            wedge_tick = eng.tick
            break
    if wedge_rid is not None:
        break



if wedge_rid is None:
    print("no wedge observed in %d ticks" % TICKS)
    raise SystemExit(0)

print("wedge first seen at tick %d, robot %s" % (wedge_tick, wedge_rid))
print("continuing 12 more ticks, printing _plan()-relevant state each tick")

for t in range(12):
    r = eng.robots[wedge_rid]
    rid = wedge_rid
    phase = eng._phase.get(rid)
    dwell = eng._dwell.get(rid, 0)
    tid = r.current_task_id
    goal = eng._goal_for(r)
    print(
        "tick=%d status=%s path_len=%d task=%s phase=%s dwell=%d "
        "quarantined=%s failed=%s goal=%s"
        % (eng.tick, r.status.value, len(r.path), tid, phase, dwell,
           r.quarantined, r.failed, goal)
    )
    if tid is None:
        print("  -- task released / robot recovered, stopping early")
        break
    eng.step()


# File contains AI-generated response based on internal company sources
