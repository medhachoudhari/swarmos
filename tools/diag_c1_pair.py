"""Per-tick ledger for one pair: verdict granted vs motion actually taken.

The waypoint-snap fix removed the free-displacement channel, and
tools/diag_c1_stepbound.py confirms zero step-authority breaches. One
collision still survives at blocked_aisle seed 17, tick 719, between R030
and R040, so the residual cause is something other than unauthorised
displacement. This probe prints, for both robots of a pair and for every
tick in a window, the verdict each was given and the distance the pair
actually ended the tick at, so the moment the true gap crosses the floor
can be attributed to a decision rather than guessed at.

Usage:
  PYTHONPATH=. python3 tools/diag_c1_pair.py <scenario> <seed> <from> <to> <ra> <rb>
"""
import math
import sys

from app.api.runner import _make_policy
from app.coordination.swarm_policy import HARD_STOP_M
from app.sim.engine import COLLISION_DISTANCE_M, SimEngine
from app.sim.scenarios import SCENARIOS


def main():
    name = sys.argv[1]
    seed = int(sys.argv[2])
    lo = int(sys.argv[3])
    hi = int(sys.argv[4])
    ra, rb = sys.argv[5], sys.argv[6]

    pol = _make_policy("swarmos", seed)
    eng = SimEngine(SCENARIOS[name], seed=seed, policy=pol, label="swarmos")

    captured = {}
    inner = pol.arbitrate

    def spy(tick, sim_time, states):
        out = inner(tick, sim_time, states)
        captured.clear()
        for rid in (ra, rb):
            v = out.get(rid)
            captured[rid] = (
                (v.kind.name, round(v.speed_scale, 3), v.conflict_with)
                if v is not None else None
            )
        return out

    pol.arbitrate = spy

    print("floor=%.3f collision=%.3f" % (HARD_STOP_M, COLLISION_DISTANCE_M))
    for _ in range(hi + 1):
        before = {r: eng.robots[r].position for r in (ra, rb)
                  if r in eng.robots}
        eng.step()
        if not (lo <= eng.tick <= hi):
            continue
        a, b = eng.robots[ra], eng.robots[rb]
        gap = math.dist(a.position, b.position)
        flag = ""
        if gap < COLLISION_DISTANCE_M:
            flag = "  <-- COLLISION"
        elif gap < HARD_STOP_M:
            flag = "  <-- inside floor"
        print("tick=%d gap=%.4f%s" % (eng.tick, gap, flag))
        for rid in (ra, rb):
            r = eng.robots[rid]
            moved = (math.dist(before[rid], r.position)
                     if rid in before else float("nan"))
            print("    %s verdict=%s moved=%.4f scale=%.3f v=%.3f st=%s "
                  "pos=(%.3f,%.3f)"
                  % (rid, captured.get(rid), moved, r.speed_scale, r.velocity,
                     r.status.name, r.position[0], r.position[1]))


if __name__ == "__main__":
    main()
