"""Localise the first SwarmOS collision tick and dump the state around it.

The powered criteria run found 7 collisions, all in the SwarmOS arm and none
in the stop-and-wait control, at 9000 ticks. Nothing appeared at 1800 ticks.
That makes it a long-horizon failure, so the first job is to find the exact
tick and the exact pair, not to theorise.

Usage:
  PYTHONPATH=. python3 tools/diag_c1_collision.py <scenario> <seed> [ticks]
"""
import math
import sys

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def closest_pair(eng):
    ids = sorted(eng.robots)
    best = (1e9, None, None)
    for i, ra in enumerate(ids):
        for rb in ids[i + 1:]:
            a, b = eng.robots[ra], eng.robots[rb]
            d = dist(a.position, b.position)
            if d < best[0]:
                best = (d, ra, rb)
    return best


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "blocked_aisle"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 29
    ticks = int(sys.argv[3]) if len(sys.argv) > 3 else 9000

    scen = SCENARIOS[name]
    eng = SimEngine(scen, seed=seed, policy=_make_policy("swarmos", seed),
                    label="swarmos")

    prev = 0
    hits = []
    for _ in range(ticks):
        eng.step()
        cur = eng.kpis()["collisions"]
        if cur != prev:
            d, ra, rb = closest_pair(eng)
            a = eng.robots[ra]
            b = eng.robots[rb]
            hits.append({
                "tick": eng.tick, "sim_time_s": round(eng.sim_time, 2),
                "count": cur, "closest_m": round(d, 4),
                "pair": (ra, rb),
                "a": (a.status, tuple(round(v, 3) for v in a.position),
                      round(a.velocity, 3)),
                "b": (b.status, tuple(round(v, 3) for v in b.position),
                      round(b.velocity, 3)),
            })
            print("COLLISION at tick=%d t=%.1fs count=%d" % (eng.tick, eng.sim_time, cur))
            print("   closest pair %s-%s at %.4f m" % (ra, rb, d))
            print("   %s: status=%s pos=%s v=%.3f"
                  % (ra, a.status, tuple(round(v, 3) for v in a.position), a.velocity))
            print("   %s: status=%s pos=%s v=%.3f"
                  % (rb, b.status, tuple(round(v, 3) for v in b.position), b.velocity))
            prev = cur

    k = eng.kpis()
    print("\n-- %s seed=%d ticks=%d" % (name, seed, ticks))
    print("   collisions=%d near_misses=%d overlap_ticks=%s"
          % (k["collisions"], k["near_misses"], k.get("overlap_ticks")))
    print("   robots_failed=%d robots_rogue=%d robots_sovereign=%d"
          % (k["robots_failed"], k["robots_rogue"], k["robots_sovereign"]))
    print("   first collision tick: %s"
          % (hits[0]["tick"] if hits else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
