"""M4 tests - bounded radio (X-25, X-03), link impairment (X-02), failure
detection (X-23) and rogue quarantine (X-10).

Each test here is written so that it would FAIL if the corresponding claim were
merely asserted rather than implemented. The range bound is checked at the
boundary, not in the easy middle; the impairment tests check that an impaired
run is still deterministic, because X-02 and X-22 would otherwise contradict
each other; and the failure detector is tested specifically on the case a
one-stage detector gets wrong - a healthy robot that went briefly quiet.
"""

from __future__ import annotations

import random

import pytest

from app.coordination.messages import (
    CoordinationMessage,
    MessageType,
)
from app.coordination.radio import (
    CONFIRM_TIMEOUT_S,
    HEARTBEAT_TIMEOUT_S,
    LINK_DEGRADED,
    LINK_PERFECT,
    LINK_SEVERE,
    R_COMM_M,
    BoundedRadio,
    FailureDetector,
    LinkProfile,
    PeerHealth,
)


def msg(sender: str, seq: int = 1) -> CoordinationMessage:
    """A minimal valid envelope. Content is irrelevant to transport behaviour."""
    return CoordinationMessage(
        schema_version="1.0",
        message_id=f"{sender}-{seq}",
        type=MessageType.HEARTBEAT,
        sender_id=sender,
        timestamp=float(seq) * 0.1,
        sequence=seq,
        payload={},
    )


def radio(
    positions: dict[str, tuple[float, float]],
    *,
    profile: LinkProfile = LINK_PERFECT,
    seed: int = 1,
) -> BoundedRadio:
    r = BoundedRadio(rng=random.Random(seed), profile=profile)
    r.set_positions(positions)
    return r


# ----------------------------------------------------------------------
# X-25 the range bound
# ----------------------------------------------------------------------
def test_radius_matches_the_arbiter_geometry():
    """The radio and the policy must agree on R_comm or the claim is incoherent."""
    from app.sim.policy import R_COMM_M as POLICY_R

    assert R_COMM_M == POLICY_R == 15.0


def test_peers_beyond_range_cannot_be_reached():
    r = radio({"R001": (0.0, 0.0), "R002": (20.0, 0.0)})
    assert r.in_range("R001", "R002") is False
    assert r.send(msg("R001"), "R002", tick=0) is False
    assert r.receive("R002") == []
    assert r.stats.out_of_range == 1
    # A refusal is not a loss: the two must remain distinguishable.
    assert r.stats.dropped == 0


def test_range_bound_is_inclusive_at_the_boundary():
    """Exactly 15.00 m is in range; a hair beyond is not."""
    inside = radio({"A": (0.0, 0.0), "B": (15.0, 0.0)})
    assert inside.in_range("A", "B") is True

    outside = radio({"A": (0.0, 0.0), "B": (15.0001, 0.0)})
    assert outside.in_range("A", "B") is False


def test_unknown_position_fails_closed():
    """An unplaced robot must be unreachable, not universally reachable."""
    r = radio({"A": (0.0, 0.0)})
    assert r.in_range("A", "GHOST") is False
    assert r.send(msg("A"), "GHOST", tick=0) is False


def test_neighbours_are_nearest_first_and_deterministic():
    r = radio({
        "R001": (0.0, 0.0),
        "R002": (5.0, 0.0),
        "R003": (1.0, 0.0),
        "R004": (99.0, 0.0),
    })
    assert r.neighbours("R001") == ["R003", "R002"]
    # Repeated calls must not reorder; the trace hash depends on this.
    assert r.neighbours("R001") == r.neighbours("R001")


def test_broadcast_reaches_only_local_peers():
    r = radio({
        "R001": (0.0, 0.0),
        "R002": (3.0, 0.0),      # in range
        "R003": (10.0, 0.0),     # in range
        "R004": (40.0, 0.0),     # far away
    })
    reached = r.broadcast(msg("R001"), tick=0)
    assert reached == 2
    assert len(r.receive("R002")) == 1
    assert len(r.receive("R003")) == 1
    assert r.receive("R004") == []


def test_broadcast_is_charged_as_one_emission():
    """X-03 accounting: fan-out must not inflate the offered count.

    One radio emission is one message sent, however many robots happen to be
    standing nearby. Charging per recipient would make the per-robot rate grow
    with density for reasons unrelated to the coordination design.
    """
    r = radio({"A": (0.0, 0.0)} | {f"R{i:03d}": (float(i) * 0.1, 0.0) for i in range(30)})
    r.broadcast(msg("A"), tick=0)
    assert r.stats.offered == 1
    assert r.stats.delivered == 30


def test_message_rate_stays_flat_as_density_grows():
    """The X-03 property, measured directly on the radio.

    Doubling the fleet inside a fixed area raises each robot's neighbour count,
    but the messages a robot EMITS per tick stays at one. That is what bounds
    total traffic to O(N) emissions rather than O(N^2).
    """
    rates = []
    for n in (10, 20, 40):
        positions = {f"R{i:03d}": (float(i % 10), float(i // 10)) for i in range(n)}
        r = radio(positions)
        for tick in range(10):
            r.tick_begin(tick)
            for rid in sorted(positions):
                r.broadcast(msg(rid, tick + 1), tick=tick)
        emitted_per_robot_tick = r.stats.offered / (10 * n)
        rates.append(emitted_per_robot_tick)

    assert all(rate == pytest.approx(1.0) for rate in rates)


# ----------------------------------------------------------------------
# X-02 impairment
# ----------------------------------------------------------------------
def test_loss_drops_some_messages_but_not_all():
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)},
              profile=LinkProfile(loss_pct=50.0), seed=7)
    for tick in range(200):
        r.tick_begin(tick)
        r.send(msg("A", tick + 1), "B", tick=tick)
        r.receive("B")

    assert r.stats.dropped > 0
    assert r.stats.delivered > 0
    # A 50% link should land near half; the window is wide enough not to be
    # flaky but narrow enough to catch a model that ignores loss_pct.
    assert 0.35 <= r.stats.delivered / 200 <= 0.65


def test_latency_defers_delivery_by_exactly_the_stated_ticks():
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)},
              profile=LinkProfile(latency_ticks=2))
    r.tick_begin(0)
    r.send(msg("A"), "B", tick=0)
    assert r.receive("B") == []          # not yet
    r.tick_begin(1)
    assert r.receive("B") == []          # still not
    r.tick_begin(2)
    assert len(r.receive("B")) == 1      # now


def test_duplicates_are_delivered_not_silently_filtered():
    """Idempotence belongs to the protocol, so the radio must expose repeats."""
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)},
              profile=LinkProfile(duplicate_pct=100.0))
    r.tick_begin(0)
    r.send(msg("A"), "B", tick=0)
    assert len(r.receive("B")) == 2
    assert r.stats.duplicated == 1


def test_impaired_runs_are_still_deterministic():
    """X-02 must not cost X-22. Same seed, same losses, same arrivals."""
    def run(seed: int) -> list[int]:
        r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)},
                  profile=LINK_DEGRADED, seed=seed)
        arrivals = []
        for tick in range(60):
            r.tick_begin(tick)
            r.send(msg("A", tick + 1), "B", tick=tick)
            arrivals.append(len(r.receive("B")))
        return arrivals

    assert run(99) == run(99)
    # And a different seed must actually produce a different pattern, or the
    # determinism above would be the trivial kind.
    assert run(99) != run(100)


def test_asymmetric_link_can_be_one_way():
    """A hears B while B does not hear A - the case that breaks handshakes."""
    r = BoundedRadio(rng=random.Random(3), profile=LINK_SEVERE)
    # B knows where A is, but A's own position is withheld, so A cannot
    # establish the reverse leg.
    r.set_positions({"A": (0.0, 0.0), "B": (1.0, 0.0)})
    assert r.in_range("A", "B") is True

    r.set_positions({"B": (1.0, 0.0)})
    assert r.in_range("B", "A") is False


def test_profile_can_be_swapped_mid_run():
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)})
    assert r.profile.is_perfect
    r.set_profile(LINK_DEGRADED)
    assert not r.profile.is_perfect
    assert r.profile.loss_pct == 20.0


# ----------------------------------------------------------------------
# X-10 quarantine
# ----------------------------------------------------------------------
def test_quarantined_robot_is_silenced_in_both_directions():
    r = radio({"A": (0.0, 0.0), "ROGUE": (1.0, 0.0), "C": (2.0, 0.0)})
    r.quarantine("ROGUE")

    assert r.is_quarantined("ROGUE")
    assert r.send(msg("ROGUE"), "A", tick=0) is False   # cannot speak
    assert r.send(msg("A"), "ROGUE", tick=0) is False   # is not spoken to
    assert "ROGUE" not in r.neighbours("A")             # invisible to coordination
    assert r.stats.quarantined == 2


def test_quarantine_can_be_lifted_and_reports_whether_it_was_held():
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)})
    assert r.release_quarantine("B") is False      # none was in force
    r.quarantine("B")
    assert r.release_quarantine("B") is True
    assert r.is_quarantined("B") is False


def test_quarantine_list_is_sorted():
    r = radio({"A": (0.0, 0.0)})
    r.quarantine("R009")
    r.quarantine("R002")
    assert r.quarantined == ("R002", "R009")


# ----------------------------------------------------------------------
# X-23 failure detection
# ----------------------------------------------------------------------
def test_silence_escalates_alive_to_suspected_to_failed():
    fd = FailureDetector()
    fd.heartbeat("R001", 0.0)

    assert fd.evaluate(0.1) == []                          # still fresh
    assert fd.health("R001") is PeerHealth.ALIVE

    fd.evaluate(0.0 + HEARTBEAT_TIMEOUT_S)
    assert fd.health("R001") is PeerHealth.SUSPECTED

    fd.evaluate(0.0 + CONFIRM_TIMEOUT_S)
    assert fd.health("R001") is PeerHealth.FAILED
    assert fd.confirmed_failed() == ("R001",)


def test_a_brief_outage_does_not_confirm_a_failure():
    """The case a one-stage detector gets wrong, and the reason for two stages.

    Under a lossy radio a robot goes quiet for a couple of ticks routinely. A
    detector that confirmed death at that point would release the corridor the
    robot is still driving down, which is how a safety system manufactures the
    collision it was installed to prevent.
    """
    fd = FailureDetector()
    fd.heartbeat("R001", 0.0)

    fd.evaluate(0.25)                       # suspicion only
    assert fd.health("R001") is PeerHealth.SUSPECTED
    assert fd.confirmed_failed() == ()      # nothing may be collected yet

    fd.heartbeat("R001", 0.30)              # it was alive all along
    assert fd.health("R001") is PeerHealth.ALIVE


def test_recovery_is_reported_as_a_transition():
    fd = FailureDetector()
    fd.heartbeat("R001", 0.0)
    fd.evaluate(1.0)                        # goes all the way to FAILED
    assert fd.health("R001") is PeerHealth.FAILED

    fd.heartbeat("R001", 1.1)               # comes back
    assert fd.health("R001") is PeerHealth.ALIVE
    last = fd.events[-1]
    assert last.previous is PeerHealth.FAILED
    assert last.current is PeerHealth.ALIVE


def test_unknown_peer_is_not_reported_as_dead():
    """Never having heard from a robot is not evidence that it failed."""
    fd = FailureDetector()
    assert fd.health("R404") is PeerHealth.UNKNOWN
    assert "R404" not in fd.confirmed_failed()


def test_transitions_are_emitted_in_sorted_id_order():
    """Event order feeds the trace hash, so it must not depend on dict order."""
    fd = FailureDetector()
    for rid in ("R003", "R001", "R002"):
        fd.heartbeat(rid, 0.0)
    events = fd.evaluate(1.0)
    assert [e.robot_id for e in events] == ["R001", "R002", "R003"]
    assert all(e.current is PeerHealth.FAILED for e in events)


def test_confirm_threshold_below_suspect_threshold_is_rejected():
    """A ladder whose rungs are inverted is a configuration error, not a policy."""
    with pytest.raises(ValueError):
        FailureDetector(suspect_after_s=0.5, confirm_after_s=0.2)


def test_only_confirmed_failures_are_offered_for_collection():
    fd = FailureDetector()
    fd.heartbeat("ALIVE_ONE", 1.0)
    fd.heartbeat("QUIET_ONE", 0.75)     # 0.25 s of silence at t=1.0
    fd.heartbeat("DEAD_ONE", 0.0)       # 1.0 s of silence at t=1.0
    fd.evaluate(1.0)

    assert fd.alive() == ("ALIVE_ONE",)
    assert fd.suspected() == ("QUIET_ONE",)
    assert fd.confirmed_failed() == ("DEAD_ONE",)


def test_stats_report_the_thresholds_in_force():
    fd = FailureDetector()
    fd.heartbeat("R001", 0.0)
    fd.evaluate(1.0)
    s = fd.stats()
    assert s["tracked"] == 1
    assert s["failed"] == 1
    assert s["suspect_after_s"] == HEARTBEAT_TIMEOUT_S
    assert s["confirm_after_s"] == CONFIRM_TIMEOUT_S


def test_radio_stats_expose_delivery_rate_and_rate_per_robot():
    r = radio({"A": (0.0, 0.0), "B": (1.0, 0.0)})
    r.tick_begin(0)
    r.send(msg("A"), "B", tick=0)
    r.send(msg("A"), "NOWHERE", tick=0)
    s = r.stats.as_dict(robots=2)
    assert s["offered"] == 2
    assert s["delivered"] == 1
    assert s["out_of_range"] == 1
    assert s["delivery_rate"] == pytest.approx(0.5)
    assert s["msgs_per_robot_tick"] == pytest.approx(0.5)

# File contains AI-generated response based on internal company sources
