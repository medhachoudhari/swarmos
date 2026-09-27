"""
Unit tests for IntentRegistry.

Validates path-version ordering, sequence tiebreaking, and CRUD operations.
"""

from __future__ import annotations

import pytest

from app.coordination.models import MovementIntent, Position
from app.coordination.messages import (
    MessageType,
    create_path_intent_message,
    create_robot_state_message,
)
from app.coordination.intent_registry import IntentRegistry


# ── helpers ──────────────────────────────────────────────────────────────

def _make_intent(
    path_version: int = 1,
    intent_id: str = "i-1",
    **kw,
) -> MovementIntent:
    defaults = dict(
        target=Position(x=10.0, y=10.0),
        path=[Position(x=5.0, y=5.0), Position(x=10.0, y=10.0)],
        eta=20.0,
        intent_id=intent_id,
        path_version=path_version,
    )
    defaults.update(kw)
    return MovementIntent(**defaults)


def _make_path_intent_msg(
    sender_id: str,
    sequence: int,
    path_version: int = 1,
    **kw,
):
    """Build a PATH_INTENT CoordinationMessage."""
    intent = _make_intent(path_version=path_version, **kw)
    return create_path_intent_message(
        message_id=f"msg-{sender_id}-{sequence}",
        sender_id=sender_id,
        timestamp=1000.0,
        sequence=sequence,
        intent=intent,
    )


# =========================================================================
# INTENT REGISTRY TESTS
# =========================================================================


class TestIntentRegistryCRUD:
    """Basic register / retrieve / remove / clear."""

    def test_register_intent(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent())
        assert reg.get("amr-01") is not None

    def test_retrieve_intent_fields(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent(path_version=3))
        assert reg.get("amr-01").path_version == 3

    def test_retrieve_missing_returns_none(self):
        reg = IntentRegistry()
        assert reg.get("amr-99") is None

    def test_remove_intent(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent())
        assert reg.remove("amr-01") is True
        assert reg.get("amr-01") is None

    def test_remove_nonexistent(self):
        reg = IntentRegistry()
        assert reg.remove("amr-99") is False

    def test_clear_registry(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent())
        reg.update("amr-02", _make_intent())
        reg.clear()
        assert reg.get_all() == {}

    def test_get_all(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent())
        reg.update("amr-02", _make_intent())
        all_intents = reg.get_all()
        assert len(all_intents) == 2
        assert "amr-01" in all_intents
        assert "amr-02" in all_intents


class TestIntentRegistryOrdering:
    """Path-version ordering and sequence tiebreaking."""

    def test_newer_path_version_replaces(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent(path_version=1))
        reg.update("amr-01", _make_intent(path_version=2))
        assert reg.get("amr-01").path_version == 2

    def test_older_path_version_does_not_overwrite(self):
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent(path_version=5))
        reg.update("amr-01", _make_intent(path_version=3))
        assert reg.get("amr-01").path_version == 5

    def test_equal_path_version_direct_replaces(self):
        """Direct update with equal path_version replaces (>= check)."""
        reg = IntentRegistry()
        reg.update("amr-01", _make_intent(path_version=2, intent_id="old"))
        reg.update("amr-01", _make_intent(path_version=2, intent_id="new"))
        assert reg.get("amr-01").intent_id == "new"

    def test_message_newer_path_version_replaces(self):
        reg = IntentRegistry()
        reg.update_from_message(_make_path_intent_msg("amr-01", sequence=1, path_version=1))
        assert reg.update_from_message(
            _make_path_intent_msg("amr-01", sequence=2, path_version=2)
        ) is True
        assert reg.get("amr-01").path_version == 2

    def test_message_older_path_version_rejected(self):
        reg = IntentRegistry()
        reg.update_from_message(_make_path_intent_msg("amr-01", sequence=1, path_version=5))
        result = reg.update_from_message(
            _make_path_intent_msg("amr-01", sequence=2, path_version=3)
        )
        assert result is False
        assert reg.get("amr-01").path_version == 5

    def test_message_equal_version_higher_sequence_accepted(self):
        reg = IntentRegistry()
        reg.update_from_message(_make_path_intent_msg("amr-01", sequence=1, path_version=3))
        assert reg.update_from_message(
            _make_path_intent_msg("amr-01", sequence=5, path_version=3)
        ) is True

    def test_message_equal_version_lower_sequence_rejected(self):
        reg = IntentRegistry()
        reg.update_from_message(_make_path_intent_msg("amr-01", sequence=5, path_version=3))
        assert reg.update_from_message(
            _make_path_intent_msg("amr-01", sequence=2, path_version=3)
        ) is False

    def test_wrong_message_type_rejected(self):
        """ROBOT_STATE messages must be rejected."""
        from app.coordination.models import AMRState, RobotStatus

        reg = IntentRegistry()
        state = AMRState(
            robot_id="amr-01",
            timestamp=1000.0,
            position=Position(x=5.0, y=5.0),
            velocity=1.0,
            heading=0.0,
            status=RobotStatus.AVAILABLE,
            battery=80.0,
        )
        msg = create_robot_state_message(
            message_id="msg-rs",
            sender_id="amr-01",
            timestamp=1000.0,
            sequence=1,
            state=state,
        )
        assert reg.update_from_message(msg) is False
