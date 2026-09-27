#!/usr/bin/env python3
"""Reproduce the wedge census table from docs/GRIDLOCK_DEFECT_20260922.md
section 2b exactly (has_task, no_path, WEDGED, moving, done) at a few tick
checkpoints, then print full internal state for the first robot that is
WEDGED for at least 3 consecutive ticks.
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
TICKS = 9000
CHECKPOINTS = {1000, 2000, 4000, 6000, 9000}

scen = type(RUSH_50)(**{**RUSH_50.__dict__, "fleet_size": FLEET})
eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

streak: dict[str, int] = {}
found = None

print("tick   has_task  no_path  WEDGED  moving  done")
for t in range(TICKS):
    eng.step()
    has_task = no_path = wedged = moving = 0
    for rid, r in eng.robots.items():
        if r.current_task_id is not None:
            has_task += 1
        empty = r.current_task_id is not None and not r.path
        if empty:
            no_path += 1
        if r.velocity > 0.01:
            moving += 1
        stuck = (
            empty and not r.failed and not r.quarantined
            and eng._dwell.get(rid, 0) == 0
        )
        if stuck:
            streak[rid] = streak.get(rid, 0) + 1
            if streak[rid] >= 3 and found is None:
                found = (rid, eng.tick)
        else:
            streak[rid] = 0
        if streak.get(rid, 0) >= 3:
            wedged += 1
    if eng.tick in CHECKPOINTS:
        print("%5d   %8d %8d %7d %7d %6d" % (
            eng.tick, has_task, no_path, wedged, moving, len(eng.completed)))

if found is None:
    print("\nno robot was WEDGED (>=3 consecutive stuck ticks) in %d ticks" % TICKS)
    raise SystemExit(0)

rid, at_tick = found
r = eng.robots[rid]
print("\nfirst WEDGED robot: %s at tick %d" % (rid, at_tick))
print("status=%s task=%s phase=%s path_len=%d dwell=%d"
      % (r.status.value, r.current_task_id, eng._phase.get(rid), len(r.path), eng._dwell.get(rid, 0)))

goal = eng._goal_for(r)
print("goal_for()        : %s" % (goal,))
avoid = eng._failed_robot_cells()
start = eng.warehouse.m_to_cell(r.x, r.y)
start_nav = nearest_navigable(eng.warehouse, start) or start
print("robot cell -> nav : %s -> %s" % (start, start_nav))
if goal is not None:
    target_nav = nearest_navigable(eng.warehouse, goal)
    print("goal cell -> nav  : %s -> %s" % (goal, target_nav))
    if target_nav is not None:
        hint = eng._avoid_hint.get(rid, set())
        detour = (avoid | hint) - {start_nav, target_nav}
        cells = find_path(eng.warehouse, start_nav, target_nav, avoid=detour)
        print("find_path(detour) -> %s" % ("None" if cells is None else "%d cells" % len(cells)))
        if cells is None:
            cells2 = find_path(eng.warehouse, start_nav, target_nav, avoid=avoid)
            print("find_path(avoid=failed only) -> %s"
                  % ("None" if cells2 is None else "%d cells" % len(cells2)))
    else:
        print("*** nearest_navigable(goal) is None")
else:
    print("*** _goal_for() is None while a task is held -- confirmed root cause")

# File contains AI-generated response based on internal company sources
