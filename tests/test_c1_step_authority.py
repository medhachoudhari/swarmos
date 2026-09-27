"""C1 regression: the engine may never move a robot further than authorised.

Both tests here FAIL on the code as it stood before the waypoint-snap fix and
pass after it. They exist because the original C1 verification ran only 1800
ticks and reported PASS, while the real failure first appears around tick 700 of
blocked_aisle seed 29 and was only caught by a 9000-tick powered run. A blind
spot that large must not be able to return.

The defect: SimRobot.step snapped onto a waypoint within WAYPOINT_TOLERANCE_M
while charging neither `moved` nor `budget`, handing the robot up to 0.08 m of
free displacement per waypoint per tick. SwarmPolicy._monitor clears a swept
envelope of scale * MAX_STEP_M, so free motion makes that envelope unsound: a
step cleared with 0.0039 m of margin reached 0.6962 m against a 0.75 m floor.
"""
import math

import pytest

from app.api.runner import _make_policy
from app.sim.clock import TICK_SECONDS
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SLACK_M = 1e-9


def _engine(name, seed):
    return SimEngine(SCENARIOS[name], seed=seed,
                     policy=_make_policy("swarmos", seed), label="swarmos")


@pytest.mark.parametrize("name,seed", [("blocked_aisle", 29), ("rush_50", 19)])
def test_displacement_never_exceeds_granted_speed(name, seed):
    """Per-tick travel stays within max_speed * speed_scale * dt, always.

    This is the contract SwarmPolicy._monitor is built on. speed_scale is read
    after the step because _apply_verdicts assigns it inside SimEngine.step and
    nothing clears it afterwards, so the post-step value is the grant that
    governed the tick that just ran.
    """
    eng = _engine(name, seed)
    for _ in range(800):
        before = {rid: r.position for rid, r in eng.robots.items()}
        eng.step()
        for rid, r in eng.robots.items():
            if rid not in before:
                continue
            allowed = r.spec.max_speed_mps * r.speed_scale * TICK_SECONDS
            moved = math.dist(before[rid], r.position)
            assert moved <= allowed + SLACK_M, (
                "%s moved %.6f m on tick %d but was granted only %.6f m"
                % (rid, moved, eng.tick, allowed)
            )


def test_blocked_aisle_seed29_is_collision_free_past_tick_700():
    """The exact run that failed C1: R007 penetrated R019 to 0.6962 m at t=700.

    Run past the failure point rather than only to it, so a fix that merely
    delays the breach by a few ticks does not pass.
    """
    eng = _engine("blocked_aisle", 29)
    eng.run(900)
    k = eng.kpis()
    assert k["collisions"] == 0, "collisions reappeared: %d" % k["collisions"]
    assert k["overlap_ticks"] == 0, (
        "robots dwelt inside the collision distance for %d tick-pairs"
        % k["overlap_ticks"]
    )


def test_blocked_aisle_seed17_is_collision_free_past_tick_719():
    """The second C1 defect: R030 reached 0.6980 m of R040 at tick 719.

    This one is not a step-authority breach at all - tools/diag_c1_stepbound.py
    reports zero overshoot on this run - so the test above cannot catch it. The
    cause was in SwarmPolicy._monitor: it bounded its own next step by
    project_step on the published movement intent, and that projection stops at
    the end of a short path. At tick 718 the projection was 0.0440 m, so every
    swept gap read back as the standing-still gap 0.7520 m and the full step was
    cleared; the engine then moved R030 0.0540 m straight at a stationary R040,
    crossing both the 0.750 m hard-stop floor and the 0.700 m collision distance
    in a single tick.

    _step_envelope now keeps the projection's direction and extends the distance
    to the MAX_STEP_M the engine can actually deliver. Run well past 719 so a fix
    that only shifts the breach later still fails.
    """
    eng = _engine("blocked_aisle", 17)
    eng.run(900)
    k = eng.kpis()
    assert k["collisions"] == 0, "collisions reappeared: %d" % k["collisions"]
    assert k["overlap_ticks"] == 0, (
        "robots dwelt inside the collision distance for %d tick-pairs"
        % k["overlap_ticks"]
    )


def test_step_envelope_never_understates_a_tick_of_motion():
    """_step_envelope is a sound upper bound and is monotone in MAX_STEP_M.

    A truncated projection must be grown to the full step the engine can
    deliver, a projection already at or beyond the step must be left alone, and
    a robot with no direction at all must be left where it stands - inventing a
    heading for a stationary robot would manufacture motion nobody intends.
    """
    from app.coordination.swarm_policy import MAX_STEP_M, _step_envelope

    here = (10.0, 4.0)

    short = _step_envelope(here, (here[0] + 0.044, here[1]))
    assert math.isclose(math.dist(here, short), MAX_STEP_M, rel_tol=1e-12)
    assert math.isclose(short[1], here[1], abs_tol=1e-12), "direction changed"

    full = (here[0] + MAX_STEP_M * 2.0, here[1])
    assert _step_envelope(here, full) == full, "a long projection was shrunk"

    assert _step_envelope(here, here) == here, "a stationary robot was moved"

    diag = _step_envelope(here, (here[0] + 0.03, here[1] + 0.04))
    assert math.isclose(math.dist(here, diag), MAX_STEP_M, rel_tol=1e-12)
    assert math.isclose((diag[1] - here[1]) / (diag[0] - here[0]), 4.0 / 3.0,
                        rel_tol=1e-12), "bearing was not preserved"
