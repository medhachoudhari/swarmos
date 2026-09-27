"""Two candidate throughput levers, measured alone and together.

Lever A - WIP cap: stop dispatching once N robots already hold a task. The
probe measured 10 -> 19 completions at cap 30, collision-free.

Lever B - replan hysteresis: a REROUTE verdict currently clears the path
EVERY tick it fires, and the fleet is doing 11 replans per tick. A path that
is rebuilt every tick is never followed, so the robot oscillates. Hysteresis
lets a fresh path survive a few ticks before another reroute may discard it.
Safety is untouched: the monitor still holds the robot at speed_scale 0 while
the conflict exists. We are only declining to THROW AWAY the route.

Both levers are applied by in-process wrapping. No repo file is edited.
"""
from __future__ import annotations

import dataclasses
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def run(arm, seed, ticks, fleet, wip_cap=None, replan_gap=0):
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy(arm, seed), label=arm)

    if wip_cap is not None:
        orig_d = eng._dispatch

        def capped():
            busy = sum(1 for r in eng.robots.values()
                       if r.current_task_id is not None)
            if busy < wip_cap:
                orig_d()

        eng._dispatch = capped

    if replan_gap > 0:
        last = {}
        orig_v = eng._apply_verdicts

        def hysteretic(verdicts):
            tick = eng.tick
            filtered = {}
            for rid, v in verdicts.items():
                if v.needs_replan and tick - last.get(rid, -10**9) < replan_gap:
                    # Keep the hold, drop only the path invalidation.
                    v = dataclasses.replace(v, needs_replan=False) \
                        if dataclasses.is_dataclass(v) else v
                elif v.needs_replan:
                    last[rid] = tick
                filtered[rid] = v
            orig_v(filtered)

        eng._apply_verdicts = hysteretic

    eng.run(ticks)
    k = eng.kpis()
    return k["tasks_complete"], k["collisions"], k["replans"]


if __name__ == "__main__":
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
    seeds = (11, 13, 17)
    configs = [
        ("control",          None, 0),
        ("wip30",              30, 0),
        ("hyst10",           None, 10),
        ("hyst25",           None, 25),
        ("wip30+hyst10",       30, 10),
        ("wip30+hyst25",       30, 25),
    ]
    print(f"fleet={fleet} ticks={ticks} seeds={seeds}")
    print(f"{'config':16s} {'done':>5s} {'coll':>5s} {'replans':>8s}")
    for name, cap, gap in configs:
        tot = coll = rep = 0
        for s in seeds:
            d, c, r = run("swarmos", s, ticks, fleet, cap, gap)
            tot += d
            coll += c
            rep += r
        flag = "" if coll == 0 else "  <-- COLLISIONS"
        print(f"{name:16s} {tot:5d} {coll:5d} {rep:8d}{flag}")
    tb = 0
    for s in seeds:
        d, c, r = run("baseline", s, ticks, fleet)
        tb += d
    print(f"{'BASELINE':16s} {tb:5d}     0")
