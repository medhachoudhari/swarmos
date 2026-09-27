"""Are robots making PROGRESS, or just moving?

The hold-structure probe showed every robot moves in both arms (median 299 vs
337 of 400 ticks) yet SWARMOS completes 4x fewer tasks. So the defect is not
starvation. This probe measures distance travelled against distance closed on
the goal - the ratio is path efficiency. A low ratio means churn: the robot
burns motion without converging.
"""
from __future__ import annotations

import math
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def probe(arm: str, seed: int, ticks: int, fleet: int):
    import dataclasses
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy(arm, seed), label=arm)

    travelled = {r: 0.0 for r in eng.robots}
    closed = {r: 0.0 for r in eng.robots}
    prev_pos = {r: (eng.robots[r].x, eng.robots[r].y) for r in eng.robots}
    prev_goal_d = {}
    path_versions = {}
    goal_changes = {r: 0 for r in eng.robots}
    prev_target = {}

    for _ in range(ticks):
        eng.step()
        for rid, r in eng.robots.items():
            px, py = prev_pos[rid]
            travelled[rid] += math.hypot(r.x - px, r.y - py)
            prev_pos[rid] = (r.x, r.y)

            tgt = eng._goal_cell.get(rid)
            if tgt is not None:
                gx, gy = eng.warehouse.cell_to_m(*tgt)
                d = math.hypot(gx - r.x, gy - r.y)
                if prev_target.get(rid) == tgt and rid in prev_goal_d:
                    closed[rid] += prev_goal_d[rid] - d
                prev_goal_d[rid] = d
                prev_target[rid] = tgt
            path_versions[rid] = r.path_version

    tot_trav = sum(travelled.values())
    tot_closed = sum(closed.values())
    eff = (tot_closed / tot_trav * 100.0) if tot_trav else 0.0
    k = eng.kpis()
    pv = sum(path_versions.values())
    print(f"--- {arm} seed={seed} fleet={fleet} ticks={ticks} ---")
    print(f"done={k['tasks_complete']}  replans={k['replans']}")
    print(f"distance travelled  = {tot_trav:9.1f} m")
    print(f"distance closed     = {tot_closed:9.1f} m")
    print(f"PATH EFFICIENCY     = {eff:9.1f} %   <-- churn indicator")
    print(f"total path_version  = {pv} ({pv/fleet:.1f} new paths per robot)")
    print()
    return eff


if __name__ == "__main__":
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    for arm in ("baseline", "swarmos"):
        probe(arm, 11, ticks, fleet)
