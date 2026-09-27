"""Was the victim peer actually visible to the arbiter on the collision tick?

The monitor can only veto against peers present in the robot's inbox, after
the STALE_TICKS freshness filter. If the stationary peer was absent from that
inbox, the floor was never applied to it and the approach was permitted. This
probe answers that one question for the known failing pair.

Usage:
  PYTHONPATH=. python3 tools/diag_c1_inbox.py <scenario> <seed> <tick> <ra> <rb>
"""
import math
import sys

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "blocked_aisle"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 29
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 700
    ra = sys.argv[4] if len(sys.argv) > 4 else "R007"
    rb = sys.argv[5] if len(sys.argv) > 5 else "R019"

    scen = SCENARIOS[name]
    pol = _make_policy("swarmos", seed)
    eng = SimEngine(scen, seed=seed, policy=pol, label="swarmos")

    for _ in range(target - 4):
        eng.step()

    for _ in range(6):
        eng.step()
        a = eng.robots.get(ra)
        b = eng.robots.get(rb)
        if a is None or b is None:
            continue
        d = math.dist(a.position, b.position)

        # Whatever the policy exposes about who each robot can hear.
        inbox_a = None
        for attr in ("_inbox", "inbox", "_views"):
            if hasattr(pol, attr):
                got = getattr(pol, attr)
                if isinstance(got, dict):
                    inbox_a = got.get(ra)
                break
        heard = None
        if isinstance(inbox_a, dict):
            heard = sorted(inbox_a)
        elif inbox_a is not None:
            heard = repr(inbox_a)[:120]

        print("tick=%d d=%.4f  %s(%s,v=%.3f) %s(%s,v=%.3f)"
              % (eng.tick, d, ra, a.status.name, a.velocity,
                 rb, b.status.name, b.velocity))
        print("    %s sees rb? %s   heard=%s"
              % (ra, (heard is not None and rb in heard) if isinstance(heard, list)
                 else "unknown", heard if isinstance(heard, list) else heard))
        print("    sovereign=%s  quarantined=%s"
              % (sorted(getattr(pol, "_sovereign", []) or []),
                 sorted(getattr(pol, "_quarantined", []) or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
