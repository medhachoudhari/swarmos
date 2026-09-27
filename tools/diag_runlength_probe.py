#!/usr/bin/env python3
"""Run-length probe: does completion count keep rising past tick 3600, or
does it freeze the way docs/GRIDLOCK_DEFECT_20260922.md measured before the
stall-release fix (fix C) landed in app/sim/engine.py?
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import RUSH_50

SEED = 18
FLEET = 50
CHECKPOINTS = [700, 1800, 3600, 5400, 9000, 14000]

scen = type(RUSH_50)(**{**RUSH_50.__dict__, "fleet_size": FLEET})
eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

print("%6s %8s %10s %10s %8s %6s %10s %8s"
      % ("tick", "sim_s", "completed", "tasks/min", "WAITING", "colls", "pending", "stalls"))

next_cp = 0
t = 0
while next_cp < len(CHECKPOINTS):
    target = CHECKPOINTS[next_cp]
    while t < target:
        eng.step()
        t += 1
    k = eng.kpis()
    statuses = {}
    for r in eng.robots.values():
        statuses[r.status.value] = statuses.get(r.status.value, 0) + 1
    print("%6d %8.1f %10d %10.2f %8d %6d %10d %8d"
          % (eng.tick, eng.sim_time, k["tasks_complete"], k["tasks_per_min"],
             statuses.get("WAITING", 0), k["collisions"], k["tasks_pending"],
             k["stall_releases"]))
    next_cp += 1

# File contains AI-generated response based on internal company sources
