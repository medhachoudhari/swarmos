"""
Unit tests for PeerStateRegistry and neighbor awareness.

Uses realistic warehouse coordinates and explicit timestamps — no
hidden wall-clock dependencies, no randomness.
"""

from __future__ import annotations

import pytest

from app.coordination.models import (
    AMRState,
    MovementIntent,
    Position,
    RobotStatus,
)
from app.coordination.messages import (
    MessageType,
    create_path_intent_message,
    create_robot_state_message,
)
from app.coordination.peer_registry import PeerStateRegistry


# ── helpers ──────────────────────────────────────────────────────────────

def _make_state(
    robot_id: str = "amr-01",
    x: float = 5.0,
    y: float = 10.0,
    timestamp: float = 1000.0,
    velocity: float = 1.0,
    **kw,
) -> AMRState:
    defaults = dict(
        robot_id=robot_id,
        timestamp=timestamp,
        position=Position(x=x, y=y),
        velocity=velocity,
        heading=0.0,
        status=RobotStatus.AVAILABLE,
        battery=80.0,
    )
    defaults.update(kw)
    return AMRState(**defaults)


def _make_robot_state_msg(
    sender_id: str,
    sequence: int,
    timestamp: float = 1000.0,
    **state_kw,
):
    """Build a ROBOT_STATE CoordinationMessage."""
    state = _make_state(robot_id=sender_id, timestamp=timestamp, **state_kw)
    return create_robot_state_message(
        message_id=f"msg-{sender_id}-{sequence}",
        sender_id=sender_id,
        timestamp=timestamp,
        sequence=sequence,
        state=state,
    )


# =========================================================================
# PEER STATE REGISTRY TESTS
# =========================================================================


class TestPeerRegistryCRUD:
    """Basic register / retrieve / update / remove / clear."""

    def test_register_peer(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01"))
        assert reg.get("amr-01") is not None
        assert reg.get("amr-01").robot_id == "amr-01"

    def test_retrieve_peer_fields(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=3.0, y=4.0))
        s = reg.get("amr-01")
        assert s.position.x == 3.0
        assert s.position.y == 4.0

    def test_retrieve_missing_returns_none(self):
        reg = PeerStateRegistry()
        assert reg.get("amr-99") is None

    def test_update_peer_overwrites(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=1.0))
        reg.update(_make_state("amr-01", x=5.0))
        assert reg.get("amr-01").position.x == 5.0

    def test_remove_existing_peer(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01"))
        assert reg.remove("amr-01") is True
        assert reg.get("amr-01") is None

    def test_remove_nonexistent_returns_false(self):
        reg = PeerStateRegistry()
        assert reg.remove("amr-99") is False

    def test_clear_registry(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01"))
        reg.update(_make_state("amr-02"))
        reg.clear()
        assert reg.get_all() == {}

    def test_get_all(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01"))
        reg.update(_make_state("amr-02"))
        all_peers = reg.get_all()
        assert len(all_peers) == 2
        assert "amr-01" in all_peers
        assert "amr-02" in all_peers


class TestPeerRegistryStale:
    """Stale-state detection using explicit current_time."""

    def test_stale_when_too_old(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", timestamp=100.0))
        assert reg.is_stale("amr-01", current_time=110.0, max_age=5.0) is True

    def test_not_stale_when_fresh(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", timestamp=100.0))
        assert reg.is_stale("amr-01", current_time=103.0, max_age=5.0) is False

    def test_unknown_peer_is_stale(self):
        reg = PeerStateRegistry()
        assert reg.is_stale("amr-99", current_time=100.0, max_age=5.0) is True


class TestPeerRegistryOrdering:
    """Sequence-based ordering for message-driven updates."""

    def test_newer_sequence_replaces(self):
        reg = PeerStateRegistry()
        reg.update_from_message(_make_robot_state_msg("amr-01", sequence=1, x=1.0))
        reg.update_from_message(_make_robot_state_msg("amr-01", sequence=2, x=5.0))
        assert reg.get("amr-01").position.x == 5.0

    def test_older_sequence_does_not_overwrite(self):
        reg = PeerStateRegistry()
        reg.update_from_message(_make_robot_state_msg("amr-01", sequence=5, x=5.0))
        result = reg.update_from_message(_make_robot_state_msg("amr-01", sequence=3, x=1.0))
        assert result is False
        assert reg.get("amr-01").position.x == 5.0

    def test_equal_sequence_does_not_overwrite(self):
        reg = PeerStateRegistry()
        reg.update_from_message(_make_robot_state_msg("amr-01", sequence=5, x=5.0))
        result = reg.update_from_message(_make_robot_state_msg("amr-01", sequence=5, x=9.0))
        assert result is False
        assert reg.get("amr-01").position.x == 5.0

    def test_direct_update_always_overwrites(self):
        """Direct update has no sequence ordering — always replaces."""
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=1.0))
        reg.update(_make_state("amr-01", x=9.0))
        assert reg.get("amr-01").position.x == 9.0

    def test_wrong_message_type_rejected(self):
        reg = PeerStateRegistry()
        intent = MovementIntent(
            target=Position(x=10.0, y=10.0),
            intent_id="i-1",
            path_version=1,
        )
        msg = create_path_intent_message(
            message_id="msg-pi",
            sender_id="amr-01",
            timestamp=1000.0,
            sequence=1,
            intent=intent,
        )
        assert reg.update_from_message(msg) is False


# =========================================================================
# NEIGHBOR AWARENESS TESTS
# =========================================================================


class TestNeighborAwareness:
    """Euclidean neighbor lookup from stored peer positions."""

    def test_nearby_peer_returned(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=0.0, y=0.0))
        reg.update(_make_state("amr-02", x=3.0, y=0.0))
        neighbors = reg.get_neighbors("amr-01", radius=5.0)
        assert len(neighbors) == 1
        assert neighbors[0].robot_id == "amr-02"

    def test_distant_peer_excluded(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=0.0, y=0.0))
        reg.update(_make_state("amr-02", x=100.0, y=0.0))
        assert len(reg.get_neighbors("amr-01", radius=5.0)) == 0

    def test_self_excluded(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=0.0, y=0.0))
        reg.update(_make_state("amr-02", x=1.0, y=0.0))
        neighbors = reg.get_neighbors("amr-01", radius=5.0)
        assert all(n.robot_id != "amr-01" for n in neighbors)

    def test_neighbor_ordering_deterministic(self):
        """Sorted by ascending distance, then by robot_id."""
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=0.0, y=0.0))
        reg.update(_make_state("amr-03", x=4.0, y=0.0))
        reg.update(_make_state("amr-02", x=2.0, y=0.0))
        neighbors = reg.get_neighbors("amr-01", radius=10.0)
        assert neighbors[0].robot_id == "amr-02"  # closer
        assert neighbors[1].robot_id == "amr-03"  # farther

    def test_configurable_radius(self):
        reg = PeerStateRegistry()
        reg.update(_make_state("amr-01", x=0.0, y=0.0))
        reg.update(_make_state("amr-02", x=3.0, y=0.0))
        assert len(reg.get_neighbors("amr-01", radius=2.0)) == 0
        assert len(reg.get_neighbors("amr-01", radius=5.0)) == 1

    def test_unknown_robot_returns_empty(self):
        reg = PeerStateRegistry()
        assert reg.get_neighbors("amr-99", radius=10.0) == []
