"""
SWARMOS Coordination — Canonical AMR State & Movement Intent Contracts

These Pydantic models define the shared data language for all SWARMOS
subsystems (simulator, path planner, coordination engine, edge-AI, dashboard).

Units & conventions
-------------------
- Position: 2-D warehouse coordinates (x, y) in metres.
- Heading:  radians, range [0, 2π). 0 = positive-X axis, π/2 = positive-Y.
- Velocity: metres per second, non-negative scalar (speed, not vector).
- Battery:  percentage, 0.0–100.0 inclusive.
- ETA:      seconds from the intent timestamp (or None when unknown).
"""

from __future__ import annotations

import enum
import math
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared validation helpers (private)
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
# Position
# ---------------------------------------------------------------------------

class Position(BaseModel):
    """2-D warehouse coordinate."""

    x: float
    y: float

    @field_validator("x")
    @classmethod
    def _x_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "x")

    @field_validator("y")
    @classmethod
    def _y_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "y")


# ---------------------------------------------------------------------------
# Robot Status
# ---------------------------------------------------------------------------

class RobotStatus(str, enum.Enum):
    """Controlled baseline states for an AMR."""

    AVAILABLE = "AVAILABLE"
    MOVING = "MOVING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CHARGING = "CHARGING"


# ---------------------------------------------------------------------------
# Movement Intent
# ---------------------------------------------------------------------------

class MovementIntent(BaseModel):
    """
    A robot's current intended movement.

    Produced by the path-planning subsystem (Member 3) or the coordination
    engine.  Consumed by the coordination engine for conflict detection,
    reservation, and negotiation in later steps.

    Fields
    ------
    target :
        Final destination waypoint.
    path :
        Ordered sequence of 2-D waypoints from current position to *target*.
    eta :
        Estimated time of arrival in seconds from the intent timestamp.
        None when the planner has not computed an estimate.
    intent_id :
        Unique identifier for this intent instance.  Allows coordination
        code to distinguish new intents from replayed / duplicate messages.
    path_version :
        Monotonically increasing version counter.  Incremented whenever the
        path is re-planned (e.g. after a reroute).  Enables stale-intent
        detection without comparing full waypoint lists.
    """

    target: Position
    path: list[Position] = Field(default_factory=list)
    eta: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Estimated arrival time in seconds (None if unknown)",
    )
    intent_id: str = Field(..., min_length=1)
    path_version: int = Field(default=1, ge=1)

    @field_validator("eta")
    @classmethod
    def _eta_must_be_finite(cls, v: float | None) -> float | None:
        if v is not None:
            _require_finite(v, "eta")
        return v

    @field_validator("intent_id")
    @classmethod
    def _intent_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "intent_id")


# ---------------------------------------------------------------------------
# AMR State
# ---------------------------------------------------------------------------

class AMRState(BaseModel):
    """
    Canonical state snapshot of a single autonomous mobile robot.

    Every subsystem that needs to know "what is robot X doing right now?"
    should consume this model.  The simulator creates it, the coordination
    engine reads it, the dashboard displays it.
    """

    robot_id: str = Field(..., min_length=1)
    timestamp: float = Field(
        ...,
        description="Unix-epoch timestamp (seconds) of this state snapshot",
    )
    position: Position
    velocity: float = Field(
        ...,
        ge=0.0,
        description="Speed in m/s (non-negative scalar)",
    )
    heading: float = Field(
        ...,
        ge=0.0,
        description="Heading in radians [0, 2π)",
    )
    status: RobotStatus
    battery: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Battery level 0–100 %",
    )
    current_task_id: Optional[str] = None
    movement_intent: Optional[MovementIntent] = None

    @field_validator("robot_id")
    @classmethod
    def _robot_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "robot_id")

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "timestamp")

    @field_validator("velocity")
    @classmethod
    def _velocity_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "velocity")

    @field_validator("heading")
    @classmethod
    def _heading_valid_range(cls, v: float) -> float:
        _require_finite(v, "heading")
        two_pi = 2.0 * math.pi
        if v < 0.0 or v >= two_pi:
            raise ValueError(
                f"heading must be in [0, 2π) radians, got {v}"
            )
        return v

    @field_validator("battery")
    @classmethod
    def _battery_must_be_finite(cls, v: float) -> float:
        return _require_finite(v, "battery")

    @field_validator("current_task_id")
    @classmethod
    def _current_task_id_not_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            _require_non_whitespace(v, "current_task_id")
        return v
