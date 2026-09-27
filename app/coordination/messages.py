"""
SWARMOS Coordination — Message Envelope & Factory Contracts

Defines a transport-agnostic message envelope that wraps every coordination
message exchanged between AMR agents, the coordination engine, and backend
services.

The envelope carries identity / ordering metadata required for future
distributed deduplication and stale-message handling:

- message_id    → deduplicate replayed messages
- sequence      → detect out-of-order delivery
- schema_version → forward-compatible schema evolution

Payloads are Pydantic models serialized to JSON-compatible dicts inside the
envelope so that the envelope itself is transport-agnostic.

Payload models
--------------
- ROBOT_STATE  → AMRState       (from models.py)
- PATH_INTENT  → MovementIntent (from models.py)

There is ONE canonical model per concept — no duplicate payload classes.
"""

from __future__ import annotations

import enum
import math
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.coordination.models import AMRState, MovementIntent


# ---------------------------------------------------------------------------
# Shared validators (private, same helpers as models.py)
# ---------------------------------------------------------------------------

def _require_finite(v: float, field_name: str) -> float:
    """Reject NaN and ±Infinity."""
    if not math.isfinite(v):
        raise ValueError(f"{field_name} must be a finite number")
    return v


def _require_non_whitespace(v: str, field_name: str) -> str:
    """Reject strings that are empty or contain only whitespace."""
    if not v.strip():
        raise ValueError(f"{field_name} must not be empty or whitespace-only")
    return v


# ---------------------------------------------------------------------------
# Message Types
# ---------------------------------------------------------------------------

class MessageType(str, enum.Enum):
    """
    Controlled set of coordination message types.

    ROBOT_STATE and PATH_INTENT were defined for Step 1.  HEARTBEAT was
    added for the bounded radio and failure detector (app/coordination/
    radio.py): it is the liveness beacon every robot emits at 10 Hz, and
    its absence is what drives the SUSPECTED -> FAILED escalation.  It
    carries no payload requirements, so adding it does not change the
    envelope schema.  Further types (CONFLICT_ALERT, RESERVATION_*, etc.)
    can be added the same way.
    """

    ROBOT_STATE = "ROBOT_STATE"
    PATH_INTENT = "PATH_INTENT"
    HEARTBEAT = "HEARTBEAT"



# ---------------------------------------------------------------------------
# Message Envelope
# ---------------------------------------------------------------------------

class CoordinationMessage(BaseModel):
    """
    Transport-agnostic message envelope for all coordination traffic.

    Every coordination message — regardless of the underlying transport
    (HTTP, WebSocket, ROS 2, Zenoh, etc.) — is wrapped in this envelope
    before being sent or after being received.

    Fields
    ------
    schema_version :
        Version string of the envelope/contract schema (e.g. "1.0").
    message_id :
        Globally unique identifier for this specific message instance.
    type :
        Controlled message type discriminator.
    sender_id :
        Identifier of the sending robot / service.
    timestamp :
        Sender-side Unix-epoch timestamp (seconds).
    sequence :
        Monotonically increasing per-sender sequence number.
        Used for stale / out-of-order detection.
    target_id :
        Intended recipient robot ID.  ``None`` indicates a broadcast.
    payload :
        Message-type-specific data serialized as a JSON-compatible dict.
    """

    schema_version: str = Field(default="1.0", min_length=1)
    message_id: str = Field(..., min_length=1)
    type: MessageType
    sender_id: str = Field(..., min_length=1)
    timestamp: float
    sequence: int = Field(..., ge=0)
    target_id: Optional[str] = None
    payload: dict[str, Any]

    @field_validator("schema_version")
    @classmethod
    def _schema_version_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "schema_version")

    @field_validator("message_id")
    @classmethod
    def _message_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "message_id")

    @field_validator("sender_id")
    @classmethod
    def _sender_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "sender_id")

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "timestamp")

    @field_validator("target_id")
    @classmethod
    def _target_id_not_whitespace(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _require_non_whitespace(v, "target_id")


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_robot_state_message(
    *,
    message_id: str,
    sender_id: str,
    timestamp: float,
    sequence: int,
    state: AMRState,
    target_id: str | None = None,
    schema_version: str = "1.0",
) -> CoordinationMessage:
    """Build a validated ROBOT_STATE envelope from an AMRState."""
    return CoordinationMessage(
        schema_version=schema_version,
        message_id=message_id,
        type=MessageType.ROBOT_STATE,
        sender_id=sender_id,
        timestamp=timestamp,
        sequence=sequence,
        target_id=target_id,
        payload=state.model_dump(mode="json"),
    )


def create_path_intent_message(
    *,
    message_id: str,
    sender_id: str,
    timestamp: float,
    sequence: int,
    intent: MovementIntent,
    target_id: str | None = None,
    schema_version: str = "1.0",
) -> CoordinationMessage:
    """Build a validated PATH_INTENT envelope from a MovementIntent."""
    return CoordinationMessage(
        schema_version=schema_version,
        message_id=message_id,
        type=MessageType.PATH_INTENT,
        sender_id=sender_id,
        timestamp=timestamp,
        sequence=sequence,
        target_id=target_id,
        payload=intent.model_dump(mode="json"),
    )

# File contains AI-generated response based on internal company sources
