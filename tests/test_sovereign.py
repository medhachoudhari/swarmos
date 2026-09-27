"""X-01 sovereign agent mode.

CLAIM UNDER TEST
  A robot that loses contact with every peer keeps working safely and alone,
  then rejoins cleanly.

The most important test in this file is the LAST one. Every other test here
proves the feature does something; that one proves it does nothing when it
should not. A behaviour change inside the arbiter that silently perturbed every
run would invalidate the deterministic-replay claim (N3) and every measurement
banked against it, so byte-identical trace hashes with no blackout injected are
the entry condition for the feature existing at all.

The confirmation window is still asserted EXACTLY, at 4 ticks and at 5, but it
is asserted against the detector's own silence streak rather than against ticks
counted from the injection. Those two are NOT the same instant: peer views
survive for STALE_TICKS after the last packet arrives, so a robot whose radio
dies at tick 2 still has fresh neighbours for three more ticks. Anchoring the
assertion on the streak keeps the claim strict - no early arm, no late arm -
without silently encoding the transport's staleness window into the test.
"""

from __future__ import annotations

from app.coordination.messages import CoordinationMessage, MessageType
from app.coordination.swarm_policy import (
    SOVEREIGN_CONFIRM_TICKS,
    SOVEREIGN_MARGIN_M,
    SOVEREIGN_SPEED_CAP,
    HARD_STOP_M,
    SwarmPolicy,
)
from app.sim import SimEngine
from app.sim.scenarios import FaultKind

CAP = 200      # step budget for the "advance until" helpers, so a broken
               # detector fails the test instead of hanging the suite.


def _engine(seed=11, policy=None):
    pol = policy if policy is not None else SwarmPolicy()
    return SimEngine(seed=seed, policy=pol), pol


def _blackout(eng, robot_id="R001", ticks=400, at=2):
    """Step to tick `at`, then cut that robot's radio."""
    while eng.tick < at:
        eng.step()
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id=robot_id, ticks=ticks)


def _step_to_streak(eng, pol, rid, target):
    """Step until the detector's silence streak reaches `target` exactly."""
    last = None
    for _ in range(CAP):
        if pol.explain(rid).get("silence_streak", 0) >= target:
            break
        last = eng.step()
    assert pol.explain(rid).get("silence_streak", 0) == target, (
        f"streak never settled on {target}"
    )
    return last


def _step_to_sovereign(eng, pol, rid):
    last = None
    for _ in range(CAP):
        last = eng.step()
        if pol.is_sovereign(rid):
            return last
    raise AssertionError(f"{rid} never entered sovereign mode in {CAP} ticks")


def _msg(sender):
    return CoordinationMessage(
        schema_version="1.0",
        message_id=f"{sender}-0-0",
        type=MessageType.ROBOT_STATE,
        sender_id=sender,
        timestamp=0.0,
        sequence=0,
        payload={},
    )


# ----------------------------------------------------------------- radio layer

def test_silence_is_symmetric_and_reversible():
    pol = SwarmPolicy()
    radio = pol.radio
    radio.silence("R001")
    assert radio.is_silenced("R001")
    assert "R001" in radio.silenced
    # A silenced robot cannot send. Charged to `dropped` on purpose, so the
    # radio stats dict shape the frontend consumes does not change.
    before = radio.stats.dropped
    assert radio.broadcast(_msg("R001"), tick=0) == 0
    assert radio.stats.dropped == before + 1
    assert radio.restore("R001") is True
    assert not radio.is_silenced("R001")
    # Restoring a robot that was never silenced is a no-op, not an error: the
    # blackout expiry path must be safe to call more than once.
    assert radio.restore("R001") is False


def test_silence_is_not_quarantine():
    """The two must stay distinguishable in the reports.

    Collapsing them would let an active attacker hide behind a broken antenna,
    which is the one thing an operator must never be unable to tell apart.
    """
    pol = SwarmPolicy()
    pol.radio.silence("R001")
    assert not pol.radio.is_quarantined("R001")
    pol.radio.quarantine("R002")
    assert not pol.radio.is_silenced("R002")


# ------------------------------------------------------------ entry and exit

def test_no_entry_one_tick_before_the_window():
    eng, pol = _engine()
    _blackout(eng)
    _step_to_streak(eng, pol, "R001", SOVEREIGN_CONFIRM_TICKS - 1)
    assert pol.is_sovereign("R001") is False
    assert pol.stats()["sovereign"]["entries"] == 0


def test_entry_exactly_at_the_window():
    eng, pol = _engine()
    _blackout(eng)
    _step_to_streak(eng, pol, "R001", SOVEREIGN_CONFIRM_TICKS)
    assert pol.is_sovereign("R001") is True
    st = pol.stats()["sovereign"]
    assert st["entries"] == 1
    assert st["robots_sovereign_now"] == 1
    assert st["robots"] == ["R001"]
    assert st["confirm_ticks"] == SOVEREIGN_CONFIRM_TICKS


def test_engine_mirrors_sovereign_onto_the_robot_and_the_kpis():
    eng, pol = _engine()
    _blackout(eng)
    snap = _step_to_sovereign(eng, pol, "R001")
    assert eng.robots["R001"].sovereign is True
    assert snap.as_dict()["kpis"]["robots_sovereign"] == 1
    wire = [r for r in snap.as_dict()["robots"] if r["id"] == "R001"][0]
    assert wire["s"] == "SOVEREIGN"


def test_quarantine_outranks_sovereign_on_the_wire():
    """A contained liar is the more urgent fact about a robot."""
    eng, pol = _engine()
    _blackout(eng)
    _step_to_sovereign(eng, pol, "R001")
    robot = eng.robots["R001"]
    assert robot.sovereign is True
    robot.quarantined = True
    assert robot.as_render_dict()["s"] == "QUARANTINED"


def test_rejoin_is_immediate_when_the_radio_comes_back():
    # Blackout shorter than the run, so the engine's own expiry path restores it.
    eng, pol = _engine()
    _blackout(eng, ticks=20)
    _step_to_sovereign(eng, pol, "R001")
    for _ in range(40):
        eng.step()
    st = pol.stats()["sovereign"]
    assert st["entries"] >= 1
    assert st["rejoins"] >= 1
    assert pol.is_sovereign("R001") is False
    assert eng.robots["R001"].sovereign is False


def test_sovereign_robot_keeps_its_task_and_still_moves():
    """The whole point. A robot that merely stopped would be useless.

    Asserted as distance travelled while sovereign, not as a velocity sample,
    because a single non-zero velocity could be the tail of motion committed
    before isolation was confirmed.
    """
    eng, pol = _engine()
    for _ in range(3):
        eng.step()
    # Pick a robot that actually has work, so "kept its task" is falsifiable.
    working = [r for r in eng.robots.values() if r.current_task_id]
    if not working:
        for _ in range(40):
            eng.step()
        working = [r for r in eng.robots.values() if r.current_task_id]
    assert working, "no robot ever received a task; the fixture is wrong"
    target = working[0]
    task_before = target.current_task_id
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id=target.robot_id, ticks=400)
    _step_to_sovereign(eng, pol, target.robot_id)
    x0, y0 = target.x, target.y
    for _ in range(40):
        eng.step()
    assert pol.is_sovereign(target.robot_id) is True
    # Task retained: sovereign mode is NOT a containment and must not release.
    assert target.current_task_id == task_before
    moved = ((target.x - x0) ** 2 + (target.y - y0) ** 2) ** 0.5
    assert moved > 0.05, f"sovereign robot did not move ({moved:.3f} m)"


def test_failed_robot_is_not_counted_as_a_rejoin():
    """A corpse did not rejoin anything, and counting it would hide a real bug."""
    eng, pol = _engine()
    _blackout(eng)
    _step_to_sovereign(eng, pol, "R001")
    before = pol.stats()["sovereign"]["rejoins"]
    eng.inject(FaultKind.ROBOT_FAILURE, robot_id="R001")
    eng.step()
    assert pol.is_sovereign("R001") is False
    assert pol.stats()["sovereign"]["rejoins"] == before


# ------------------------------------------------------------- the envelope

def test_the_envelope_is_strictly_tighter():
    """Floor and cap are the two halves of the claim, so assert both."""
    assert SOVEREIGN_MARGIN_M > 0.0
    assert 0.0 < SOVEREIGN_SPEED_CAP < 1.0
    st = SwarmPolicy().stats()["sovereign"]
    assert st["margin_m"] == SOVEREIGN_MARGIN_M
    assert st["speed_cap"] == SOVEREIGN_SPEED_CAP
    # The widened floor must still be below the aisle pitch, or a sovereign
    # robot could never pass anything and the feature would be a stop dressed up.
    assert HARD_STOP_M + SOVEREIGN_MARGIN_M < 1.20


def test_sovereign_speed_is_capped():
    eng, pol = _engine()
    _blackout(eng)
    _step_to_sovereign(eng, pol, "R001")
    for _ in range(30):
        eng.step()
    v = pol._last_decisions.get("R001")
    assert v is not None
    scale = v.speed_scale or 0.0
    assert scale <= SOVEREIGN_SPEED_CAP + 1e-9, f"scale {scale} exceeds the cap"


def test_explain_names_sovereign_mode():
    """The Decision Inspector must be able to justify the slower step."""
    eng, pol = _engine()
    _blackout(eng)
    _step_to_sovereign(eng, pol, "R001")
    ex = pol.explain("R001")
    assert ex["sovereign"] is True
    assert ex["silence_streak"] >= SOVEREIGN_CONFIRM_TICKS


def test_blackout_on_a_policy_without_a_radio_is_refused_not_crashed():
    from app.sim import NoOpPolicy
    eng = SimEngine(seed=11, policy=NoOpPolicy())
    eng.step()
    out = eng.inject(FaultKind.COMM_BLACKOUT)
    assert out["fault_kind"] == FaultKind.COMM_BLACKOUT.value
    assert out["applied"] is False


# --------------------------------------------------------- the invariance gate

def test_trace_hash_is_unchanged_when_no_blackout_is_injected():
    """The entry gate for this whole feature (N3).

    tools/probe_isolation.py measured ZERO zero-peer robot-ticks in 30,000
    robot-ticks of a normal run, so the detector provably cannot arm without an
    injected blackout. This asserts the consequence rather than trusting the
    measurement: two identical un-injected runs must agree, and no robot may
    have entered sovereign mode in either.
    """
    hashes = []
    for _ in range(2):
        pol = SwarmPolicy()
        eng = SimEngine(seed=11, policy=pol)
        snap = None
        for _ in range(120):
            snap = eng.step()
        assert pol.stats()["sovereign"]["entries"] == 0
        assert pol.stats()["sovereign"]["ticks"] == 0
        assert snap.as_dict()["kpis"]["robots_sovereign"] == 0
        hashes.append(snap.as_dict()["trace_hash"])
    assert hashes[0] == hashes[1]
