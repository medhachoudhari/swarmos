#!/usr/bin/env python3
"""The wedge census (diag_wedge_census.py) shows completions freeze at 10 from
tick ~4000 to 9000 (matching docs/GRIDLOCK_DEFECT_20260922.md) even though no
robot has a *literally* empty path for 3+ consecutive ticks. So the stall is
not "no path ever assigned" - it's "gets a path, but never completes it".
This script tracks one of the 41 has-task robots at tick 4000 across many
ticks: position, path length, velocity, verdict kind, replans, to see whether
it is making net progress toward its goal or oscillating in place.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import RUSH_50

SEED = 18
FLEET = 50
WARMUP = 4000
WATCH = 400

scen = type(RUSH_50)(**{**RUSH_50.__dict__, "fleet_size": FLEET})
eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED), label="swarmos")

for _ in range(WARMUP):
    eng.step()

# Pick a robot that has a task right now and is not moving.
target_rid = None
for rid, r in eng.robots.items():
    if r.current_task_id is not None and r.velocity < 0.01 and not r.failed and not r.quarantined:
        target_rid = rid
        break

if target_rid is None:
    print("all busy robots were moving at tick %d - pick any" % eng.tick)
    for rid, r in eng.robots.items():
        if r.current_task_id is not None:
            target_rid = rid
            break

print("watching robot %s starting at tick %d" % (target_rid, eng.tick))
print("%6s %8s %6s %6s %8s %10s %8s" % ("tick", "x", "y", "path", "vel", "verdict", "replans"))

start_pos = (eng.robots[target_rid].x, eng.robots[target_rid].y)
last_replans = eng.replans

for i in range(WATCH):
    eng.step()
    r = eng.robots.get(target_rid)
    if r is None:
        print("robot vanished")
        break
    verdicts = getattr(eng, "_last_verdicts", {})
    v = verdicts.get(target_rid)
    vk = v.kind.value if v is not None else "-"
    if i % 10 == 0:
        print("%6d %8.2f %6.2f %6d %8.3f %10s %8d"
              % (eng.tick, r.x, r.y, len(r.path), r.velocity, vk, eng.replans))
    if r.current_task_id is None:
        print("tick %d: robot %s completed/released its task" % (eng.tick, target_rid))
        break

end_pos = (eng.robots[target_rid].x, eng.robots[target_rid].y) if target_rid in eng.robots else None
print("")
print("start pos: %s  end pos: %s" % (start_pos, end_pos))
if end_pos:
    import math
    dist = math.hypot(end_pos[0] - start_pos[0], end_pos[1] - start_pos[1])
    print("net displacement over %d ticks (%d s): %.2f m" % (WATCH, WATCH // 10, dist))
print("replans consumed by fleet over this window: %d" % (eng.replans - last_replans))

# File contains AI-generated response based on internal company sources
