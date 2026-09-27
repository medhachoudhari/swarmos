"""Is the fleet over-committed? Measure work-in-progress vs completion.

tasks_active was pinned at exactly 50 of 50 in every run. If the dispatcher
assigns a task to every robot the instant it is free, then all 50 robots are
simultaneously converging on 50 different pick cells, guaranteeing maximum
mutual interference. A congestion-collapse signature.

This probe caps concurrent assignments and measures the effect. It patches
NOTHING - the cap is applied by monkey-patching is_available_for_work in
process, so the repo is untouched while the hypothesis is tested.
"""
from __future__ import annotations

import dataclasses
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def run(arm: str, seed: int, ticks: int, fleet: int, wip_cap):
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy(arm, seed), label=arm)

    if wip_cap is not None:
        orig = eng._dispatch

        def capped():
            busy = sum(1 for r in eng.robots.values()
                       if r.current_task_id is not None)
            if busy >= wip_cap:
                return
            orig()

        eng._dispatch = capped

    eng.run(ticks)
    k = eng.kpis()
    return k["tasks_complete"], k["collisions"], k["tasks_active"]


if __name__ == "__main__":
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    print(f"fleet={fleet} ticks={ticks} scenario=rush_50")
    print(f"{'cap':>6s} {'arm':10s} {'s11':>5s} {'s17':>5s} {'TOT':>5s} {'coll':>5s}")
    for cap in (None, 30, 20, 12, 8):
        for arm in ("swarmos",):
            tot = 0
            colls = 0
            row = []
            for seed in (11, 17):
                d, c, a = run(arm, seed, ticks, fleet, cap)
                row.append(d)
                tot += d
                colls += c
            label = "none" if cap is None else str(cap)
            print(f"{label:>6s} {arm:10s} {row[0]:5d} {row[1]:5d} {tot:5d} {colls:5d}")
