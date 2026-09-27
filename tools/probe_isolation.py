"""Probe: how often does a robot hear no peer at all?

X-01 (sovereign agent mode) must trigger on genuine total isolation. Before
wiring any behaviour change this measures the natural incidence of "zero fresh
peers in my own inbox" in a normal run, because if that is common then a
tightened envelope keyed on it would fire constantly and perturb every replay.
"""
import sys
sys.path.insert(0, ".")

from app.sim.engine import SimEngine
from app.coordination.swarm_policy import SwarmPolicy
from app.coordination.models import RobotStatus

ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 600
fleet = int(sys.argv[2]) if len(sys.argv) > 2 else 8

pol = SwarmPolicy()
eng = SimEngine(seed=11, policy=pol)
if hasattr(eng, "resize_fleet"):
    eng.resize_fleet(fleet)

alone_ticks = 0
robot_ticks = 0
max_streak = {}
streak = {}
for _ in range(ticks):
    eng.step()
    for rid, inbox in pol._views.items():
        fresh = pol._fresh(inbox)
        peers = sum(1 for p in fresh if p != rid)
        robot_ticks += 1
        if peers == 0:
            alone_ticks += 1
            streak[rid] = streak.get(rid, 0) + 1
            max_streak[rid] = max(max_streak.get(rid, 0), streak[rid])
        else:
            streak[rid] = 0

print("robots          :", len(eng.robots))
print("robot-ticks     :", robot_ticks)
print("zero-peer ticks :", alone_ticks,
      "(%.1f%%)" % (100.0 * alone_ticks / max(1, robot_ticks)))
print("longest zero-peer streak per robot:",
      dict(sorted(max_streak.items())))
print("robots with streak >= 5 :",
      sum(1 for v in max_streak.values() if v >= 5))
print("impairment reaches policy? radio profile:",
      pol.radio._profile.as_dict() if hasattr(pol.radio, "_profile") else "n/a")
