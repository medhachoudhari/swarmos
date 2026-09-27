#!/usr/bin/env python3
"""Find a robot whose path stays EMPTY for several consecutive ticks while it
still holds a task (the real permanent-wedge signature from
docs/GRIDLOCK_DEFECT_20260922.md), then print the engine-internal state on
every one of those ticks to see exactly which _plan() guard is blocking it.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import RUSH_50
from app.sim.pathfinding import find_path, nearest_navigable

SEED = 18
FLEET = 50
TICKS = 4000
PERSIST_TICKS = 5  # consecutive ticks with no path to count as a real wedge

scen = type(RUSH_50)(**{**RUSH_50.__dict__, "fleet_size": FLEET})
eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

streak: dict[str, int] = {}
found = None

for t in range(TICKS):
    eng.step()
    for rid, r in eng.robots.items():
        no_path_task = (
            r.current_task_id is not None and not r.path
            and not r.failed and not r.quarantined
            and eng._dwell.get(rid, 0) == 0
        )
        if no_path_task:
            streak[rid] = streak.get(rid, 0) + 1
            if streak[rid] >= PERSIST_TICKS:
                found = rid
                break
        else:
            streak[rid] = 0
    if found:
        print("tick %d: robot %s has had an empty path for >= %d consecutive ticks"
              % (eng.tick, found, PERSIST_TICKS))
        break

if not found:
    print("no persistent (>= %d tick) wedge observed in %d ticks" % (PERSIST_TICKS, TICKS))
    raise SystemExit(0)

rid = found
r = eng.robots[rid]
print("")
print("robot=%s task=%s phase=%s status=%s" % (rid, r.current_task_id, eng._phase.get(rid), r.status.value))
print("hint pending      : %s" % eng._avoid_hint.get(rid))
print("dwell             : %s" % eng._dwell.get(rid, 0))

goal = eng._goal_for(r)
print("goal_for()        : %s" % (goal,))
avoid = eng._failed_robot_cells()
print("failed_robot_cells: %s" % avoid)

start = eng.warehouse.m_to_cell(r.x, r.y)
start_nav = nearest_navigable(eng.warehouse, start) or start
print("robot cell        : %s -> nearest_navigable %s" % (start, start_nav))

if goal is not None:
    target_nav = nearest_navigable(eng.warehouse, goal)
    print("goal cell          : %s -> nearest_navigable %s" % (goal, target_nav))
    if target_nav is not None:
        hint = eng._avoid_hint.get(rid, set())
        detour = (avoid | hint) - {start_nav, target_nav}
        cells = find_path(eng.warehouse, start_nav, target_nav, avoid=detour)
        print("find_path(with detour=%s) -> %s" % (detour, "None" if cells is None else "%d cells" % len(cells)))
        cells2 = find_path(eng.warehouse, start_nav, target_nav, avoid=avoid)
        print("find_path(avoid failed-only)      -> %s"
              % ("None" if cells2 is None else "%d cells" % len(cells2)))
    else:
        print("*** target_nav is None -- nearest_navigable() found no reachable cell for the goal")
else:
    print("*** _goal_for() returned None while robot still holds a task -- THIS is the bug:"
          " _plan() has nothing to do for this robot even though it needs a path.")

# File contains AI-generated response based on internal company sources
