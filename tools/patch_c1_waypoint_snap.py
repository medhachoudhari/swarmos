"""C1 fix A: charge the waypoint snap against the tick's motion budget.

SimRobot.step snapped onto a waypoint whenever the remaining leg was under
WAYPOINT_TOLERANCE_M, consuming neither `budget` nor `moved`. That handed the
robot up to WAYPOINT_TOLERANCE_M of free displacement per waypoint per tick, on
top of whatever its speed allowed. Measured effect: R007 moved 0.0777 m on a
tick whose charged budget was 0.016 m.

Free displacement makes the coordination layer's swept envelope unsound by
construction: the monitor clears `scale * MAX_STEP_M` of motion, and the engine
may then move further than that, so a step cleared with 0.0039 m of margin
penetrated the 0.75 m floor to 0.6962 m. That is the C1 failure.

The fix keeps the snap - its anti-drift purpose is real - but makes it
affordable-only and charges it, so displacement per tick is bounded by
velocity * dt for every robot on every tick.
"""
import ast
import io
import sys

PATH = "app/sim/robot.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 occurrence, found %d" % (label, count)
    return text.replace(old, new)


OLD = """            if leg <= WAYPOINT_TOLERANCE_M:
                # Snap exactly onto the waypoint so accumulated float error
                # cannot drift a robot off the aisle centreline.
                self.x, self.y = wx, wy
                self.path.pop(0)
                continue
"""

NEW = """            if leg <= WAYPOINT_TOLERANCE_M and leg <= budget:
                # Snap exactly onto the waypoint so accumulated float error
                # cannot drift a robot off the aisle centreline.
                #
                # The snap is charged against the budget, and is taken only when
                # the budget can afford it. It used to be free: neither `moved`
                # nor `budget` was touched, so a robot could gain up to
                # WAYPOINT_TOLERANCE_M of displacement per waypoint per tick on
                # top of whatever its speed allowed. That broke the invariant the
                # coordination layer depends on - that granting speed_scale f
                # moves a robot at most f * MAX_STEP_M - and it cost real
                # collisions: a step the safety monitor cleared with 0.0039 m of
                # margin overshot into the 0.75 m hard-stop floor, reaching
                # 0.6962 m. See docs/SUCCESS_CRITERIA_VERIFICATION.md, C1.
                #
                # An unaffordable near-waypoint falls through to the ratio branch
                # below and snaps on a later tick, so the anti-drift guarantee is
                # kept without granting motion nobody authorised.
                self.x, self.y = wx, wy
                self.path.pop(0)
                moved += leg
                budget -= leg
                continue
"""


def main():
    text = io.open(PATH).read()
    text = sub(text, OLD, NEW, "waypoint snap charges budget")
    ast.parse(text)
    io.open(PATH, "w").write(text)
    print("patched %s" % PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
