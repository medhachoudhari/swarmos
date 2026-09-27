"""Measure the bound the arbiter actually grants, not the post-step velocity.

robot.step zeroes self.velocity after the robot arrives (`if not self.path`),
and _drain zeroes it on a flat battery, so the POST-step velocity understates
what was authorised for that tick. Using it flagged 24 phantom breaches of
exactly 0.200 m - legitimate full-speed steps whose velocity was cleared on
arrival.

The sound bound is the one coordination relies on: a robot granted speed_scale f
may travel at most max_speed * f * dt in a tick. That is the quantity the swept
envelope in SwarmPolicy._monitor is built on, so it is the one worth asserting.
"""
import ast
import io
import sys

PATH = "tools/diag_c1_stepbound.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 occurrence, found %d" % (label, count)
    return text.replace(old, new)


OLD = """    worst = 0.0
    worst_at = None
    breaches = 0
    for _ in range(ticks):
        before = {rid: r.position for rid, r in eng.robots.items()}
        eng.step()
        for rid, r in eng.robots.items():
            if rid not in before:
                continue
            # velocity is the post-step value, which is the speed the engine
            # actually integrated this tick, so this is the honest allowance.
            allowed = r.velocity * TICK_SECONDS + SLACK_M
            moved = math.dist(before[rid], r.position)
"""

NEW = """    worst = 0.0
    worst_at = None
    breaches = 0
    for _ in range(ticks):
        before = {rid: (r.position, r.spec.max_speed_mps * r.speed_scale)
                  for rid, r in eng.robots.items()}
        eng.step()
        for rid, r in eng.robots.items():
            if rid not in before:
                continue
            # The bound coordination relies on: a robot granted speed_scale f
            # travels at most max_speed * f * dt in one tick. Deliberately NOT
            # the post-step velocity - robot.step zeroes that on arrival and on
            # a flat battery, which understates the allowance and manufactures
            # phantom breaches out of legitimate full-speed steps.
            pos0, cap = before[rid]
            allowed = cap * TICK_SECONDS + SLACK_M
            moved = math.dist(pos0, r.position)
"""

OLD2 = """                worst, worst_at = excess, (eng.tick, rid, moved, allowed)"""
NEW2 = """                worst, worst_at = excess, (eng.tick, rid, round(moved, 6),
                                           round(allowed, 6))"""


def main():
    text = io.open(PATH).read()
    text = sub(text, OLD, NEW, "use granted speed cap as the bound")
    text = sub(text, OLD2, NEW2, "round the reported worst case")
    ast.parse(text)
    io.open(PATH, "w").write(text)
    print("patched %s" % PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
