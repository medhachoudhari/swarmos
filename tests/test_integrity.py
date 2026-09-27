"""Tests for X-10 / N9: message integrity and adversarial containment.

The tests that matter here are not the happy paths. They are:

  - a single accuser can NEVER contain anyone (otherwise compromising one robot
    lets an attacker silence the fleet one peer at a time),
  - an honest fleet under realistic sensor noise is never accused of anything
    (a containment mechanism with false positives removes fleet capacity for
    free and would rightly be switched off),
  - integrity=False changes NOTHING, including the trace hash,
  - a contained robot is actually stopped and its work returned, rather than
    merely labelled.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.coordination.integrity import (
    QUORUM,
    CLAIM_TOLERANCE_M,
    Accusation,
    ContainmentEvent,
    IntegrityVerdict,
    MessageAuthenticator,
    SentinelCouncil,
    canonical_bytes,
    sign_bytes,
)
from app.coordination.messages import CoordinationMessage, MessageType
from app.coordination.swarm_policy import SwarmPolicy
from app.sim.engine import SimEngine
from app.sim.scenarios import get_scenario
from app.sim.sensing import SENSING_REALISTIC


def _msg(sender="R001", seq=0, payload=None, mid=None):
    return CoordinationMessage(
        schema_version="1.0",
        message_id=mid or f"{sender}-{seq}",
        type=MessageType.ROBOT_STATE,
        sender_id=sender,
        timestamp=1.0,
        sequence=seq,
        payload=payload if payload is not None else {"k": 1},
    )


# --------------------------------------------------------------- canonical form
def test_canonical_bytes_is_stable_across_key_order():
    a = canonical_bytes(message_id="m", sender_id="R001", msg_type="robot_state",
                        sequence=1, target_id=None, payload={"a": 1, "b": 2})
    b = canonical_bytes(message_id="m", sender_id="R001", msg_type="robot_state",
                        sequence=1, target_id=None, payload={"b": 2, "a": 1})
    assert a == b


def test_canonical_bytes_excludes_timestamp():
    """A signature must survive clock normalisation in transit."""
    body = canonical_bytes(message_id="m", sender_id="R001",
                           msg_type="robot_state", sequence=1,
                           target_id=None, payload={})
    assert b"timestamp" not in body


def test_canonical_bytes_changes_when_the_payload_changes():
    a = canonical_bytes(message_id="m", sender_id="R001", msg_type="t",
                        sequence=1, target_id=None, payload={"x": 1.0})
    b = canonical_bytes(message_id="m", sender_id="R001", msg_type="t",
                        sequence=1, target_id=None, payload={"x": 1.5})
    assert a != b


def test_sign_bytes_is_deterministic():
    assert sign_bytes(b"k", b"body") == sign_bytes(b"k", b"body")


# ------------------------------------------------------------- authentication
def test_a_signed_message_verifies():
    auth = MessageAuthenticator()
    auth.enrol(["R001"])
    m = _msg()
    auth.sign(m)
    assert auth.verify(m) == IntegrityVerdict.OK
    assert auth.stats.verified == 1


def test_an_unenrolled_sender_is_unknown_not_merely_invalid():
    """Impersonation and a bad signature are different faults."""
    auth = MessageAuthenticator()
    m = _msg(sender="R999")
    auth.sign(m)
    assert auth.verify(m) == IntegrityVerdict.UNKNOWN_SENDER


def test_an_unsigned_message_is_reported_as_unsigned():
    auth = MessageAuthenticator()
    auth.enrol(["R001"])
    assert auth.verify(_msg()) == IntegrityVerdict.UNSIGNED


def test_a_tampered_payload_fails_verification():
    auth = MessageAuthenticator()
    auth.enrol(["R001"])
    m = _msg(payload={"x": 1.0})
    sig = auth.sign(m)
    tampered = _msg(payload={"x": 99.0}, mid=m.message_id)
    assert auth.verify(tampered, signature=sig) == IntegrityVerdict.BAD_SIGNATURE


def test_one_robot_cannot_forge_a_peers_signature():
    """Per-robot key derivation: holding your own key is not holding a peer's."""
    auth = MessageAuthenticator()
    auth.enrol(["R001", "R002"])
    victim = _msg(sender="R002")
    forged = sign_bytes(auth.key_for("R001"), canonical_bytes(
        message_id=victim.message_id, sender_id="R002",
        msg_type=MessageType.ROBOT_STATE.value, sequence=victim.sequence,
        target_id=None, payload=victim.payload))
    assert auth.verify(victim, signature=forged) == IntegrityVerdict.BAD_SIGNATURE


def test_revocation_makes_a_former_member_unknown():
    auth = MessageAuthenticator()
    auth.enrol(["R001"])
    m = _msg()
    auth.sign(m)
    auth.revoke("R001")
    assert auth.verify(m) == IntegrityVerdict.UNKNOWN_SENDER


def test_rejection_reasons_are_counted_by_kind():
    auth = MessageAuthenticator()
    auth.verify(_msg(sender="R900"))
    auth.verify(_msg(sender="R901"))
    d = auth.stats.as_dict()
    assert d["rejected"] == 2
    assert d["reasons"][IntegrityVerdict.UNKNOWN_SENDER] == 2


# ------------------------------------------------------------------- the quorum
def test_a_single_accuser_can_never_contain_anyone():
    """The property the whole design rests on."""
    c = SentinelCouncil()
    for i in range(50):
        assert c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, i) is None
    assert c.contained == ()


def test_quorum_of_distinct_witnesses_contains():
    c = SentinelCouncil()
    assert c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1) is None
    ev = c.accuse("R002", "R009", c.REASON_FALSE_CLAIM, 2)
    assert isinstance(ev, ContainmentEvent)
    assert ev.action == "quarantine"
    assert ev.witnesses == ("R001", "R002")
    assert c.is_contained("R009")


def test_witnesses_are_a_set_so_repetition_cannot_manufacture_quorum():
    c = SentinelCouncil(quorum=3)
    for i in range(20):
        c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, i)
    assert not c.is_contained("R009")


def test_accusations_under_different_reasons_do_not_pool():
    """Otherwise one witness could reach quorum alone by varying the charge."""
    c = SentinelCouncil()
    c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1)
    c.accuse("R001", "R009", c.REASON_FLOOD, 2)
    assert not c.is_contained("R009")


def test_self_accusation_is_discarded():
    c = SentinelCouncil(quorum=1)
    assert c.accuse("R009", "R009", c.REASON_FALSE_CLAIM, 1) is None
    assert c.contained == ()


def test_sub_quorum_suspicion_is_visible_to_the_operator():
    c = SentinelCouncil()
    c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1)
    assert c.pending() == {"R009:false_position_claim": ["R001"]}


def test_pending_clears_once_contained():
    c = SentinelCouncil()
    c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1)
    c.accuse("R002", "R009", c.REASON_FALSE_CLAIM, 2)
    assert c.pending() == {}


# ------------------------------------------------------------------- the audits
def test_a_claim_inside_tolerance_is_not_an_accusation():
    c = SentinelCouncil()
    ev = c.audit_claim(accuser="R001", accused="R002", claimed=(10.0, 10.0),
                       observed=(10.0 + CLAIM_TOLERANCE_M * 0.5, 10.0), tick=1)
    assert ev is None
    assert c.accusation_log == []


def test_an_unobserved_peer_is_never_accused():
    """Occlusion is not evidence of lying."""
    c = SentinelCouncil(quorum=1)
    assert c.audit_claim(accuser="R001", accused="R002",
                         claimed=(0.0, 0.0), observed=None, tick=1) is None
    assert c.contained == ()


def test_a_claim_beyond_tolerance_accuses_and_explains_itself():
    c = SentinelCouncil(quorum=1)
    ev = c.audit_claim(accuser="R001", accused="R002", claimed=(0.0, 0.0),
                       observed=(5.0, 0.0), tick=7)
    assert ev is not None and ev.reason == c.REASON_FALSE_CLAIM
    assert "5.00" in ev.detail and "tolerance" in ev.detail


def test_flooding_is_detected_and_honest_traffic_is_not():
    c = SentinelCouncil(quorum=1, flood_per_tick=10)
    evs = c.audit_traffic(accuser="R001",
                          counts={"R002": 3, "R003": 40}, tick=1)
    assert [e.robot_id for e in evs] == ["R003"]


def test_an_unknown_sender_is_charged_with_impersonation():
    c = SentinelCouncil(quorum=1)
    ev = c.audit_signature(accuser="R001", accused="R999",
                           verdict=IntegrityVerdict.UNKNOWN_SENDER, tick=1)
    assert ev is not None and ev.reason == c.REASON_IMPERSONATION


def test_a_valid_signature_produces_no_accusation():
    c = SentinelCouncil(quorum=1)
    assert c.audit_signature(accuser="R001", accused="R002",
                             verdict=IntegrityVerdict.OK, tick=1) is None


# -------------------------------------------------------------- rehabilitation
def test_a_contained_robot_can_earn_release():
    c = SentinelCouncil(rehabilitation_ticks=5)
    c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1)
    c.accuse("R002", "R009", c.REASON_FALSE_CLAIM, 1)
    assert c.is_contained("R009")
    released = []
    for t in range(5):
        released += c.tick_clean(["R009"], t)
    assert [e.action for e in released] == ["release"]
    assert not c.is_contained("R009")


def test_fresh_misbehaviour_restarts_the_rehabilitation_clock():
    c = SentinelCouncil(rehabilitation_ticks=4)
    c.accuse("R001", "R009", c.REASON_FALSE_CLAIM, 1)
    c.accuse("R002", "R009", c.REASON_FALSE_CLAIM, 1)
    for t in range(3):
        c.tick_clean(["R009"], t)
    c.reset_clean_streak("R009")
    assert c.tick_clean(["R009"], 9) == []
    assert c.is_contained("R009")


def test_a_released_robot_can_be_contained_again():
    c = SentinelCouncil(rehabilitation_ticks=2)
    for w in ("R001", "R002"):
        c.accuse(w, "R009", c.REASON_FALSE_CLAIM, 1)
    for t in range(2):
        c.tick_clean(["R009"], t)
    assert not c.is_contained("R009")
    for w in ("R003", "R004"):
        c.accuse(w, "R009", c.REASON_FALSE_CLAIM, 20)
    assert c.is_contained("R009")


def test_clear_resets_everything():
    c = SentinelCouncil()
    for w in ("R001", "R002"):
        c.accuse(w, "R009", c.REASON_FALSE_CLAIM, 1)
    c.clear()
    assert c.contained == () and c.accusation_log == [] and c.log == []


# ------------------------------------------------------- integration: inert off
def test_integrity_off_does_not_change_the_trace_hash():
    """A safety feature that changes unrelated scenarios is not free."""
    a = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=False))
    b = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=False))
    a.run(60)
    b.run(60)
    assert a.trace_hash == b.trace_hash


def test_integrity_off_signs_and_verifies_nothing():
    e = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=False))
    e.run(40)
    s = e.policy.stats()["integrity"]
    assert s["enabled"] is False
    assert s["auth"]["signed"] == 0
    assert s["council"]["accusations"] == 0


def test_an_honest_fleet_is_never_accused():
    e = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=True))
    e.run(120)
    s = e.policy.stats()["integrity"]
    assert s["auth"]["signed"] > 0
    assert s["auth"]["verified"] > 0
    assert s["auth"]["rejected"] == 0
    assert s["council"]["accusations"] == 0
    assert s["council"]["contained"] == []


def test_realistic_sensor_noise_causes_no_false_accusations():
    """Drift is bounded far below the claim tolerance; if that ever stops being
    true the mechanism starts quarantining robots for having wheels."""
    spec = dataclasses.replace(get_scenario("rush_50"),
                               sensing=SENSING_REALISTIC)
    e = SimEngine(spec, seed=42, policy=SwarmPolicy(integrity=True))
    e.run(400)
    s = e.policy.stats()["integrity"]
    assert s["council"]["accusations"] == 0, s["council"]["pending"]
    assert s["council"]["contained"] == []


# ------------------------------------------------- integration: rogue contained
def _rogue_run(ticks=120, integrity=True):
    e = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=integrity))
    e.run(20)
    res = e.inject("ROGUE_ROBOT")
    e.run(ticks)
    return e, res["robot_id"]


def test_a_spoofing_rogue_is_contained():
    e, target = _rogue_run()
    assert e.policy.council.is_contained(target)


def test_only_the_rogue_is_contained():
    e, target = _rogue_run()
    assert list(e.policy.council.contained) == [target]


def test_the_containment_event_names_its_witnesses_and_its_evidence():
    e, target = _rogue_run()
    ev = [x for x in e.policy.council.log if x.robot_id == target][0]
    assert len(ev.witnesses) >= QUORUM
    assert target not in ev.witnesses      # nobody testifies against themselves
    assert "observed" in ev.detail


def test_a_contained_robot_is_actually_stopped_and_gives_up_its_work():
    e, target = _rogue_run()
    r = e.robots[target]
    assert r.quarantined is True
    assert r.velocity == 0.0
    assert r.current_task_id is None


def test_a_contained_robot_is_cut_off_at_the_radio():
    e, target = _rogue_run()
    assert e.policy.radio.is_quarantined(target)
    assert target not in e.policy.radio.neighbours("R001")


def test_a_contained_robot_is_not_left_in_any_peers_local_view():
    """Its last lie must not go on steering the fleet after it is cut off."""
    e, target = _rogue_run()
    for rid, inbox in e.policy._views.items():
        assert target not in inbox, f"{rid} still believes {target}"


def test_the_rogue_is_reported_as_quarantined_to_the_ui():
    e, target = _rogue_run()
    row = [r for r in e.robots[target].as_render_dict().items()]
    d = dict(row)
    assert d["s"] == "QUARANTINED"
    assert d["rogue"] is True
    assert d["cl"] is not None      # the claim is shown, not hidden


def test_an_honest_robot_reports_no_claim_divergence():
    e = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=True))
    e.run(30)
    assert all(r.as_render_dict()["cl"] is None for r in e.robots.values())


def test_containment_is_recorded_as_an_event():
    e, target = _rogue_run()
    kinds = {ev.get("kind") for ev in e.events}
    assert "containment" in kinds


def test_a_rogue_lies_to_peers_but_not_to_the_scorer():
    """The spoof must never touch true state, or the collision count is fiction."""
    e, target = _rogue_run(ticks=5)
    r = e.robots[target]
    assert (r.spoof_x, r.spoof_y) != (0.0, 0.0)
    assert r.claimed_x != pytest.approx(r.x)
    obs = e.observations()
    seen = [v[target] for k, v in obs.items() if target in v]
    assert all(s == pytest.approx((r.x, r.y)) for s in seen)


def test_containment_does_not_break_the_safety_invariant():
    e, _ = _rogue_run(ticks=200)
    assert e.kpis()["collisions"] == 0


def test_the_run_stays_deterministic_with_a_rogue_and_containment():
    a, _ = _rogue_run(ticks=100)
    b, _ = _rogue_run(ticks=100)
    assert a.trace_hash == b.trace_hash


def test_stats_publishes_the_containment_record():
    e, target = _rogue_run()
    s = e.policy.stats()["integrity"]
    assert s["enabled"] is True
    assert s["robots_contained"] >= 1
    assert s["accusations"] >= QUORUM
    assert target in s["council"]["contained"]
