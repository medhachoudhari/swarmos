"""Make the safety monitor's own swept envelope a sound upper bound.

Root cause of the residual C1 collision, blocked_aisle seed 17, R030 vs R040:

  tick=718 intent=yes step_len=0.0440 rest_gap=0.7520
      swept_gaps 1.00:0.7520 0.75:0.7520 0.50:0.7520 0.25:0.7520
      verdict=PROCEED speed_scale=1.0
  ENGINE tick=719 moved=0.0540 ... d 0.7520 -> 0.6980   <-- collision

The monitor projected R030's published movement intent and got a step of only
0.0440 m, so every swept gap read back as the standing-still gap and the full
step was cleared. The engine then moved R030 0.0540 m straight at R040 and the
pair crossed both the 0.750 m floor and the 0.700 m collision distance in one
tick.

The projected intent is NOT an upper bound on a tick of motion. It is the path
the robot last published, and it can be shorter than the distance the robot is
able to travel - the path is consumed as the robot moves, a replan can shorten
it, and the reported copy the monitor reads can lag the true one. Whenever the
projection is shorter than MAX_STEP_M the envelope silently understates the
approach, and an understated envelope makes the whole floor unsound: no margin
survives if the monitor is measuring the wrong segment.

The fix keeps the direction the projection gives - that is the part it knows -
and extends the endpoint out to the full MAX_STEP_M the engine could actually
deliver. It is strictly conservative: the envelope only ever grows, so no
motion that used to be refused becomes allowed.

Deliberately NOT changed: the `granted` segments published for peers. Those are
scaled by a decided speed and assuming more peer motion than was granted was
already measured to cost 31 percent of robot-ticks to phantom motion. This
patch only fixes the bound a robot applies to ITSELF, which is the one that has
to hold for the floor to mean anything.
"""
import ast
import io

PATH = "app/coordination/swarm_policy.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 occurrence, found %d" % (label, count)
    return text.replace(old, new)


OLD = """        here = (me.position.x, me.position.y)
        full = project_step(me, MAX_STEP_M)
        rest: Segment = (here, here)
"""

NEW = '''        here = (me.position.x, me.position.y)
        full = _step_envelope(here, project_step(me, MAX_STEP_M))
        rest: Segment = (here, here)
'''

HELPER = '''def _step_envelope(
    here: tuple[float, float], projected: tuple[float, float]
) -> tuple[float, float]:
    """Endpoint of the furthest step the engine could actually deliver.

    `project_step` walks the robot's published movement intent, so it returns
    the end of the path when the path is shorter than the step. That is not an
    upper bound on one tick of motion: the path is consumed as the robot moves,
    a replan can shorten it, and the reported copy lags the true one. Treating
    it as a bound cost a collision - see tools/patch_c1_sound_envelope.py for
    the trace - because a projection of 0.044 m cleared a full-speed step that
    moved 0.054 m and crossed the hard-stop floor.

    Keep the direction, which the projection does know, and extend the distance
    to the MAX_STEP_M the engine can deliver. A robot with no direction at all
    is left where it stands: inventing a heading for a stationary robot would
    manufacture motion nobody intends and wedge the aisle.
    """
    dx, dy = projected[0] - here[0], projected[1] - here[1]
    reach = math.hypot(dx, dy)
    if reach <= 1e-12 or reach >= MAX_STEP_M:
        return projected
    grow = MAX_STEP_M / reach
    return (here[0] + dx * grow, here[1] + dy * grow)


'''

ANCHOR = "class SwarmPolicy"


def main():
    text = io.open(PATH).read()
    text = sub(text, OLD, NEW, "monitor envelope")

    assert text.count(ANCHOR) == 1, "anchor for helper is not unique"
    text = text.replace(ANCHOR, HELPER + ANCHOR)

    ast.parse(text)
    io.open(PATH, "w").write(text)
    print("patched %s" % PATH)


if __name__ == "__main__":
    main()
