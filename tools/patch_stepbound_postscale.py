"""Read the granted speed cap AFTER the step, not before it.

_apply_verdicts sets speed_scale INSIDE SimEngine.step, so sampling it before
the call reads the previous tick's grant. Nothing resets speed_scale after the
robots move, so the post-step value is exactly what was authorised for the tick
that just ran. Sampling it early reported 566 phantom breaches of up to 0.012 m,
all of them robots whose grant was raised on the very tick being measured.
"""
import ast
import io
import sys

PATH = "tools/diag_c1_stepbound.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 occurrence, found %d" % (label, count)
    return text.replace(old, new)


OLD = """        before = {rid: (r.position, r.spec.max_speed_mps * r.speed_scale)
                  for rid, r in eng.robots.items()}
"""
NEW = """        before = {rid: r.position for rid, r in eng.robots.items()}
"""

OLD2 = """            pos0, cap = before[rid]
            allowed = cap * TICK_SECONDS + SLACK_M
            moved = math.dist(pos0, r.position)
"""
NEW2 = """            # speed_scale is read AFTER the step because _apply_verdicts sets
            # it inside SimEngine.step, and nothing resets it once the robots
            # have moved, so this is the grant that governed this very tick.
            cap = r.spec.max_speed_mps * r.speed_scale
            allowed = cap * TICK_SECONDS + SLACK_M
            moved = math.dist(before[rid], r.position)
"""


def main():
    text = io.open(PATH).read()
    text = sub(text, OLD, NEW, "snapshot positions only")
    text = sub(text, OLD2, NEW2, "cap from post-step speed_scale")
    ast.parse(text)
    io.open(PATH, "w").write(text)
    print("patched %s" % PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
