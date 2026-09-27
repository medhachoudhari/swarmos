"""
Unit tests for SWARMOS coordination contract layer.

Tests real validation behaviour of Pydantic models — not just object
instantiation.  Covers Position, AMRState, MovementIntent, CoordinationMessage,
JSON serialization round-trips, broadcast semantics, and factory behaviour.
"""

from __future__ import annotations

import math
import uuid

import pytest
from pydantic import ValidationError

from app.coordination.models import (
    AMRState,
    MovementIntent,
    Position,
    RobotStatus,
)
from app.coordination.messages import (
    CoordinationMessage,
    MessageType,
    create_path_intent_message,
    create_robot_state_message,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _make_position(x: float = 5.0, y: float = 10.0) -> Position:
    return Position(x=x, y=y)


def _make_intent(**overrides) -> MovementIntent:
    defaults = dict(
        target=_make_position(15.0, 8.0),
        path=[_make_position(10.0, 5.0), _make_position(12.0, 5.0), _make_position(15.0, 8.0)],
        eta=42.0,
        intent_id="intent-001",
        path_version=1,
    )
    defaults.update(overrides)
    return MovementIntent(**defaults)


def _make_state(**overrides) -> AMRState:
    defaults = dict(
        robot_id="amr-01",
        timestamp=1700000000.0,
        position=_make_position(),
        velocity=1.5,
        heading=0.0,
        status=RobotStatus.AVAILABLE,
        battery=85.0,
        current_task_id=None,
        movement_intent=None,
    )
    defaults.update(overrides)
    return AMRState(**defaults)


def _make_envelope(**overrides) -> CoordinationMessage:
    defaults = dict(
        schema_version="1.0",
        message_id=str(uuid.uuid4()),
        type=MessageType.ROBOT_STATE,
        sender_id="amr-01",
        timestamp=1700000000.0,
        sequence=0,
        target_id=None,
        payload={"robot_id": "amr-01"},
    )
    defaults.update(overrides)
    return CoordinationMessage(**defaults)


# =========================================================================
# POSITION TESTS
# =========================================================================

class TestPosition:
    """Tests 1–5: Position validation."""

    def test_valid_position_accepted(self):
        pos = _make_position(3.5, -7.2)
        assert pos.x == 3.5
        assert pos.y == -7.2

    def test_nan_x_rejected(self):
        with pytest.raises(ValidationError):
            _make_position(x=float("nan"))

    def test_infinity_x_rejected(self):
        with pytest.raises(ValidationError):
            _make_position(x=float("inf"))

    def test_nan_y_rejected(self):
        with pytest.raises(ValidationError):
            _make_position(y=float("nan"))

    def test_infinity_y_rejected(self):
        with pytest.raises(ValidationError):
            _make_position(y=float("-inf"))


# =========================================================================
# AMR STATE TESTS
# =========================================================================

class TestAMRState:
    """Tests 6–23: AMRState validation."""

    def test_valid_state_accepted(self):
        state = _make_state()
        assert state.robot_id == "amr-01"
        assert state.status == RobotStatus.AVAILABLE
        assert state.battery == 85.0
        assert state.velocity == 1.5
        assert state.position.x == 5.0
        assert state.position.y == 10.0

    def test_empty_robot_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(robot_id="")

    def test_whitespace_only_robot_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(robot_id="   ")

    def test_battery_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(battery=-1.0)

    def test_battery_above_100_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(battery=100.1)

    def test_invalid_status_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(status="EXPLODING")

    def test_negative_velocity_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(velocity=-0.5)

    def test_nan_velocity_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(velocity=float("nan"))

    def test_infinity_velocity_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(velocity=float("inf"))

    def test_heading_zero_accepted(self):
        state = _make_state(heading=0.0)
        assert state.heading == 0.0

    def test_heading_just_below_two_pi_accepted(self):
        just_below = 2.0 * math.pi - 1e-10
        state = _make_state(heading=just_below)
        assert math.isclose(state.heading, just_below)

    def test_negative_heading_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(heading=-0.1)

    def test_heading_equals_two_pi_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(heading=2.0 * math.pi)

    def test_heading_above_two_pi_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(heading=7.0)

    def test_nan_heading_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(heading=float("nan"))

    def test_infinity_heading_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(heading=float("inf"))

    def test_nan_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(timestamp=float("nan"))

    def test_infinity_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            _make_state(timestamp=float("inf"))


# =========================================================================
# MOVEMENT INTENT TESTS
# =========================================================================

class TestMovementIntent:
    """Tests 24–34: MovementIntent validation."""

    def test_valid_intent_accepted(self):
        intent = _make_intent()
        assert intent.target.x == 15.0
        assert len(intent.path) == 3
        assert intent.eta == 42.0
        assert intent.intent_id == "intent-001"
        assert intent.path_version == 1

    def test_negative_eta_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(eta=-1.0)

    def test_eta_zero_accepted(self):
        intent = _make_intent(eta=0.0)
        assert intent.eta == 0.0

    def test_eta_none_accepted(self):
        intent = _make_intent(eta=None)
        assert intent.eta is None

    def test_nan_eta_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(eta=float("nan"))

    def test_infinity_eta_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(eta=float("inf"))

    def test_empty_intent_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(intent_id="")

    def test_whitespace_only_intent_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(intent_id="   ")

    def test_path_version_one_accepted(self):
        intent = _make_intent(path_version=1)
        assert intent.path_version == 1

    def test_path_version_zero_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(path_version=0)

    def test_path_version_negative_rejected(self):
        with pytest.raises(ValidationError):
            _make_intent(path_version=-1)


# =========================================================================
# COORDINATION MESSAGE TESTS
# =========================================================================

class TestCoordinationMessage:
    """Tests 35–47: CoordinationMessage (envelope) validation."""

    def test_valid_robot_state_message_accepted(self):
        state = _make_state()
        msg = create_robot_state_message(
            message_id="msg-001",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=1,
            state=state,
        )
        assert msg.type == MessageType.ROBOT_STATE
        assert msg.payload["robot_id"] == "amr-01"
        assert msg.payload["battery"] == 85.0
        assert msg.target_id is None

    def test_valid_path_intent_message_accepted(self):
        intent = _make_intent()
        msg = create_path_intent_message(
            message_id="msg-002",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=2,
            intent=intent,
        )
        assert msg.type == MessageType.PATH_INTENT
        assert msg.payload["intent_id"] == "intent-001"
        assert msg.payload["path_version"] == 1

    def test_invalid_message_type_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(type="SELF_DESTRUCT")

    def test_empty_message_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(message_id="")

    def test_whitespace_only_message_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(message_id="   ")

    def test_empty_sender_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(sender_id="")

    def test_whitespace_only_sender_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(sender_id="   ")

    def test_nan_message_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(timestamp=float("nan"))

    def test_infinity_message_timestamp_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(timestamp=float("inf"))

    def test_none_target_id_accepted_as_broadcast(self):
        msg = _make_envelope(target_id=None)
        assert msg.target_id is None

    def test_empty_target_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(target_id="")

    def test_whitespace_only_target_id_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(target_id="   ")

    def test_negative_sequence_rejected(self):
        with pytest.raises(ValidationError):
            _make_envelope(sequence=-1)


# =========================================================================
# SERIALIZATION TESTS
# =========================================================================

class TestSerialization:
    """Tests 48–53: JSON round-trip verification."""

    def test_position_json_roundtrip(self):
        pos = _make_position(3.14, 2.71)
        json_str = pos.model_dump_json()
        reconstructed = Position.model_validate_json(json_str)
        assert reconstructed.x == pos.x
        assert reconstructed.y == pos.y

    def test_movement_intent_json_roundtrip(self):
        intent = _make_intent(intent_id="intent-rt", path_version=5)
        json_str = intent.model_dump_json()
        reconstructed = MovementIntent.model_validate_json(json_str)
        assert reconstructed.intent_id == "intent-rt"
        assert reconstructed.path_version == 5
        assert reconstructed.target.x == intent.target.x
        assert len(reconstructed.path) == len(intent.path)
        assert reconstructed.eta == intent.eta

    def test_amr_state_json_roundtrip(self):
        state = _make_state(
            movement_intent=_make_intent(),
            current_task_id="task-42",
        )
        json_str = state.model_dump_json()
        reconstructed = AMRState.model_validate_json(json_str)

        assert reconstructed.robot_id == state.robot_id
        assert reconstructed.timestamp == state.timestamp
        assert reconstructed.position.x == state.position.x
        assert reconstructed.position.y == state.position.y
        assert reconstructed.velocity == state.velocity
        assert reconstructed.heading == state.heading
        assert reconstructed.status == state.status
        assert reconstructed.battery == state.battery
        assert reconstructed.current_task_id == "task-42"
        assert reconstructed.movement_intent is not None
        assert reconstructed.movement_intent.intent_id == state.movement_intent.intent_id

    def test_robot_state_message_json_roundtrip(self):
        state = _make_state()
        msg = create_robot_state_message(
            message_id="msg-rt-env",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=10,
            state=state,
            target_id="amr-02",
        )
        json_str = msg.model_dump_json()
        reconstructed = CoordinationMessage.model_validate_json(json_str)

        assert reconstructed.message_id == "msg-rt-env"
        assert reconstructed.type == MessageType.ROBOT_STATE
        assert reconstructed.sender_id == "amr-01"
        assert reconstructed.sequence == 10
        assert reconstructed.target_id == "amr-02"
        assert reconstructed.schema_version == "1.0"
        assert reconstructed.payload["robot_id"] == "amr-01"

    def test_path_intent_message_json_roundtrip(self):
        intent = _make_intent(intent_id="intent-rt", path_version=3)
        msg = create_path_intent_message(
            message_id="msg-pi-rt",
            sender_id="amr-03",
            timestamp=1700000000.0,
            sequence=7,
            intent=intent,
        )
        json_str = msg.model_dump_json()
        reconstructed = CoordinationMessage.model_validate_json(json_str)

        assert reconstructed.type == MessageType.PATH_INTENT
        assert reconstructed.payload["intent_id"] == "intent-rt"
        assert reconstructed.payload["path_version"] == 3

    def test_intent_id_path_version_survive_serialization(self):
        intent = _make_intent(intent_id="intent-xyz", path_version=7)
        json_str = intent.model_dump_json()
        reconstructed = MovementIntent.model_validate_json(json_str)

        assert reconstructed.intent_id == "intent-xyz"
        assert reconstructed.path_version == 7

        # Also through a full message round-trip
        msg = create_path_intent_message(
            message_id="msg-surv",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=5,
            intent=intent,
        )
        msg_json = msg.model_dump_json()
        msg_reconstructed = CoordinationMessage.model_validate_json(msg_json)

        assert msg_reconstructed.payload["intent_id"] == "intent-xyz"
        assert msg_reconstructed.payload["path_version"] == 7


# =========================================================================
# FACTORY BEHAVIOUR TESTS
# =========================================================================

class TestFactory:
    """Tests 54–56: Factory typed-input enforcement."""

    def test_robot_state_factory_requires_amr_state(self):
        """Factory accepts AMRState, produces ROBOT_STATE envelope."""
        state = _make_state()
        msg = create_robot_state_message(
            message_id="msg-f1",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=0,
            state=state,
        )
        assert msg.type == MessageType.ROBOT_STATE
        # Verify payload contains AMRState fields
        assert "robot_id" in msg.payload
        assert "battery" in msg.payload
        assert "position" in msg.payload

    def test_path_intent_factory_requires_movement_intent(self):
        """Factory accepts MovementIntent, produces PATH_INTENT envelope."""
        intent = _make_intent()
        msg = create_path_intent_message(
            message_id="msg-f2",
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=0,
            intent=intent,
        )
        assert msg.type == MessageType.PATH_INTENT
        # Verify payload contains MovementIntent fields
        assert "intent_id" in msg.payload
        assert "path_version" in msg.payload
        assert "target" in msg.payload

    def test_invalid_payload_cannot_be_created_through_factory(self):
        """
        Creating an invalid AMRState or MovementIntent raises
        ValidationError before the factory can produce an envelope.
        """
        with pytest.raises(ValidationError):
            bad_state = AMRState(
                robot_id="",  # invalid
                timestamp=1700000000.0,
                position=_make_position(),
                velocity=1.0,
                heading=0.0,
                status=RobotStatus.AVAILABLE,
                battery=50.0,
            )

        with pytest.raises(ValidationError):
            bad_intent = MovementIntent(
                target=_make_position(),
                intent_id="",  # invalid
                path_version=1,
            )


# =========================================================================
# ADDITIONAL: null current_task_id
# =========================================================================

def test_null_current_task_id_valid():
    state = _make_state(current_task_id=None)
    assert state.current_task_id is None

    state2 = _make_state(current_task_id="task-99")
    assert state2.current_task_id == "task-99"


# =========================================================================
# ADDITIONAL: dict reconstruction
# =========================================================================

def test_json_dict_reconstruction():
    state = _make_state()
    as_dict = state.model_dump()

    assert isinstance(as_dict, dict)
    assert isinstance(as_dict["position"], dict)
    assert isinstance(as_dict["status"], str)

    reconstructed = AMRState.model_validate(as_dict)
    assert reconstructed.robot_id == state.robot_id
    assert reconstructed.battery == state.battery


# =========================================================================
# ADDITIONAL: missing required fields
# =========================================================================

def test_missing_required_fields_rejected():
    with pytest.raises(ValidationError):
        CoordinationMessage(
            type=MessageType.ROBOT_STATE,
            sender_id="amr-01",
            timestamp=1700000000.0,
            sequence=0,
            payload={},
            # message_id intentionally missing
        )

    with pytest.raises(ValidationError):
        CoordinationMessage(
            message_id="msg-x",
            type=MessageType.ROBOT_STATE,
            timestamp=1700000000.0,
            sequence=0,
            payload={},
            # sender_id intentionally missing
        )
