"""What did the arbiter actually compute for the mover on the collision tick?

Peer visibility, staleness, containment and sovereign mode are already ruled
out. This probe wraps CoordinationPolicy.arbitrate and, for the named pair over
a window of ticks, prints exactly the quantities the monitor decides on:

  - whether the mover's AMRState carries a movement_intent at all, because
    project_step returns the robot's own position when it does not, which makes
    the swept segment degenerate and the gap test trivially pass
  - the projected full step and its length
  - the rest gap and the swept gap at every MONITOR_SCALES fraction
  - the verdict the policy returned for the mover
  - the displacement the engine then actually applied, so the monitor's step
    model can be compared against the integrator

Usage:
  PYTHONPATH=. python3 tools/diag_c1_monitor.py <scenario> <seed> <tick> <ra> <rb>
"""
import math
import sys

from app.api.runner import _make_policy
from app.coordination.swarm_policy import (
    CONFLICT_M,
    HARD_STOP_M,
    INTERACT_RADIUS_M,
    MAX_STEP_M,
    MONITOR_SCALES,
)
from app.sim.engine import SimEngine
from app.sim.policy import _project_step as project_step
from app.sim.policy import _segment_distance as segment_distance
from app.sim.scenarios import SCENARIOS


def lerp(here, end, scale):
    return (here[0] + (end[0] - here[0]) * scale,
            here[1] + (end[1] - here[1]) * scale)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "blocked_aisle"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 29
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 700
    ra = sys.argv[4] if len(sys.argv) > 4 else "R007"
    rb = sys.argv[5] if len(sys.argv) > 5 else "R019"

    lo, hi = target - 3, target + 1
    print("floor=%.3f CONFLICT_M=%.3f MAX_STEP_M=%.3f INTERACT_RADIUS_M=%.3f"
          % (HARD_STOP_M, CONFLICT_M, MAX_STEP_M, INTERACT_RADIUS_M))
    print("scales=%s" % (MONITOR_SCALES,))

    scen = SCENARIOS[name]
    pol = _make_policy("swarmos", seed)
    eng = SimEngine(scen, seed=seed, policy=pol, label="swarmos")

    orig = pol.arbitrate

    def wrapped(tick, sim_time, states):
        verdicts = orig(tick, sim_time, states)
        if lo <= tick <= hi:
            me = states.get(ra)
            pe = states.get(rb)
            if me is not None and pe is not None:
                here = (me.position.x, me.position.y)
                there = (pe.position.x, pe.position.y)
                full = project_step(me, MAX_STEP_M)
                rest = (here, here)
                theirs = (there, there)
                print("  tick=%d intent=%s step_len=%.4f rest_gap=%.4f"
                      % (tick, "yes" if me.movement_intent is not None else "NONE",
                         math.dist(here, full), segment_distance(rest, theirs)))
                if me.movement_intent is not None:
                    npath = len(me.movement_intent.path)
                    print("      path_pts=%d first=%s"
                          % (npath,
                             "(%.3f,%.3f)" % (me.movement_intent.path[0].x,
                                              me.movement_intent.path[0].y)
                             if npath else "none"))
                gaps = ["%.2f:%.4f" % (s, segment_distance((here, lerp(here, full, s)),
                                                           theirs))
                        for s in MONITOR_SCALES]
                print("      swept_gaps %s" % " ".join(gaps))
                print("      verdict=%r" % (verdicts.get(ra),))
        return verdicts

    pol.arbitrate = wrapped

    for _ in range(lo):
        eng.step()

    for _ in range(hi - lo + 1):
        a = eng.robots[ra]
        b = eng.robots[rb]
        before = a.position
        d0 = math.dist(a.position, b.position)
        eng.step()
        after = a.position
        print("  ENGINE tick=%d moved=%.4f scale=%.3f v=%.4f d %.4f -> %.4f"
              % (eng.tick, math.dist(before, after), a.speed_scale, a.velocity,
                 d0, math.dist(a.position, b.position)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
