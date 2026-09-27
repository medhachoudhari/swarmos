"""Is per-tick displacement now bounded by what the arbiter authorised?

Two questions, one run:
  1. does any robot move further in a tick than velocity * dt (plus float slack)?
  2. does the known failing scenario/seed still record a collision?

The first is the invariant the coordination layer's swept envelope relies on.
Before the waypoint-snap fix it was violated routinely - a robot could gain up
to WAYPOINT_TOLERANCE_M of free displacement per waypoint per tick.

Usage:
  PYTHONPATH=. python3 tools/diag_c1_stepbound.py <scenario> <seed> [ticks]
"""
import math
import sys

from app.api.runner import _make_policy
from app.sim.clock import TICK_SECONDS
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SLACK_M = 1e-9


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "blocked_aisle"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 29
    ticks = int(sys.argv[3]) if len(sys.argv) > 3 else 900

    scen = SCENARIOS[name]
    eng = SimEngine(scen, seed=seed, policy=_make_policy("swarmos", seed),
                    label="swarmos")

    worst = 0.0
    worst_at = None
    breaches = 0
    for _ in range(ticks):
        before = {rid: r.position for rid, r in eng.robots.items()}
        eng.step()
        for rid, r in eng.robots.items():
            if rid not in before:
                continue
            # The bound coordination relies on: a robot granted speed_scale f
            # travels at most max_speed * f * dt in one tick. Deliberately NOT
            # the post-step velocity - robot.step zeroes that on arrival and on
            # a flat battery, which understates the allowance and manufactures
            # phantom breaches out of legitimate full-speed steps.
            # speed_scale is read AFTER the step because _apply_verdicts sets
            # it inside SimEngine.step, and nothing resets it once the robots
            # have moved, so this is the grant that governed this very tick.
            cap = r.spec.max_speed_mps * r.speed_scale
            allowed = cap * TICK_SECONDS + SLACK_M
            moved = math.dist(before[rid], r.position)
            excess = moved - allowed
            if excess > worst:
                worst, worst_at = excess, (eng.tick, rid, round(moved, 6),
                                           round(allowed, 6))
            if excess > 1e-6:
                breaches += 1

    k = eng.kpis()
    print("%s seed=%d ticks=%d" % (name, seed, ticks))
    print("  worst overshoot beyond velocity*dt : %.6f m" % worst)
    print("  worst case                         : %s" % (worst_at,))
    print("  ticks-robots exceeding the bound   : %d" % breaches)
    print("  collisions=%d near_misses=%d overlap_ticks=%d"
          % (k["collisions"], k["near_misses"], k["overlap_ticks"]))
    print("  tasks_complete=%d avg_completion_s=%s"
          % (k["tasks_complete"], k["avg_completion_s"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
