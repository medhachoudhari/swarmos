"""
SWARMOS Coordination — Spatio-Temporal Conflict Detection

Deterministic, explainable conflict detection based on:

- current robot positions  (``AMRState``)
- planned waypoint paths   (``MovementIntent``)
- speed / ETA timing model
- configurable spatial and temporal thresholds

Timing model
------------
For each robot:

1. Full path = ``[current_position] + MovementIntent.path``
   (consecutive duplicate waypoints removed).
2. Speed = ``AMRState.velocity`` if > 0, else ``default_speed``.
3. Segment duration = Euclidean length / speed.
4. If ``MovementIntent.eta`` is provided and > 0, scale all segment
   durations proportionally so that total travel time equals ``eta``.
5. Segment timestamps are cumulative from ``AMRState.timestamp``.

Conflict types
--------------
- **VERTEX**:     Both robots predicted to occupy the same location at
                  overlapping times.
- **EDGE_SWAP**:  Robots traverse the same corridor segment in opposite
                  directions with overlapping traversal intervals.
- **PROXIMITY**:  Robots' paths come within ``spatial_threshold`` during
                  temporal overlap (general case).

Architecture boundary
---------------------
This module does **not** decide winner, priority, WAIT, YIELD, or REROUTE.
It only reports predicted conflicts for the downstream reservation /
negotiation layer.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.coordination.models import AMRState, MovementIntent, Position


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ConflictDetectionConfig(BaseModel):
    """Tunable parameters for spatio-temporal conflict detection."""

    spatial_threshold: float = Field(
        default=1.5,
        gt=0.0,
        description=(
            "Safety distance in metres.  Two robots whose predicted "
            "positions come within this distance are in conflict.  "
            "Default 1.5 m assumes ~1 m robot diameter + 0.5 m margin."
        ),
    )
    temporal_threshold: float = Field(
        default=0.5,
        ge=0.0,
        description=(
            "Minimum meaningful temporal overlap in seconds.  Segment "
            "pairs whose overlap is shorter than this are skipped."
        ),
    )
    default_speed: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Fallback speed in m/s when AMRState.velocity is zero "
            "(e.g. robot is stationary but has a movement intent)."
        ),
    )


# ---------------------------------------------------------------------------
# Conflict type enum
# ---------------------------------------------------------------------------

class ConflictType(str, enum.Enum):
    """Controlled conflict classification."""

    VERTEX = "VERTEX"
    EDGE_SWAP = "EDGE_SWAP"
    PROXIMITY = "PROXIMITY"


# ---------------------------------------------------------------------------
# Conflict result
# ---------------------------------------------------------------------------

class ConflictResult(BaseModel):
    """
    Structured description of a single predicted spatio-temporal conflict.

    Contains enough information for downstream reservation / negotiation
    logic to reason about the conflict without re-running detection.
    """

    robot_a_id: str
    robot_b_id: str
    conflict_type: ConflictType
    location: Position
    time_window_start: float
    time_window_end: float
    min_distance: float = Field(ge=0.0)
    robot_a_path_version: int
    robot_b_path_version: int


# ---------------------------------------------------------------------------
# Internal: timed segment
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimedSegment:
    """A straight-line path segment with start/end positions and times."""

    start: Position
    end: Position
    t_start: float
    t_end: float


# ---------------------------------------------------------------------------
# Private geometry helpers
# ---------------------------------------------------------------------------

def _dist(a: Position, b: Position) -> float:
    """Euclidean distance between two 2-D positions."""
    dx = a.x - b.x
    dy = a.y - b.y
    return math.sqrt(dx * dx + dy * dy)


def _position_at_time(seg: TimedSegment, t: float) -> Position:
    """Linear interpolation along a segment at a given time."""
    dur = seg.t_end - seg.t_start
    if dur <= 0:
        return seg.start
    alpha = max(0.0, min(1.0, (t - seg.t_start) / dur))
    return Position(
        x=seg.start.x + alpha * (seg.end.x - seg.start.x),
        y=seg.start.y + alpha * (seg.end.y - seg.start.y),
    )


def _min_distance_during_overlap(
    a_seg: TimedSegment,
    b_seg: TimedSegment,
    t_start: float,
    t_end: float,
) -> tuple[float, float]:
    """
    Minimum Euclidean distance between two linearly-moving robots
    during the time interval ``[t_start, t_end]``.

    Both robots move in straight lines along their respective segments.
    The inter-robot distance is a quadratic function of time, so the
    minimum is found analytically.

    Returns ``(min_distance, time_of_minimum)``.
    """
    if t_start >= t_end:
        return float("inf"), t_start

    overlap_dur = t_end - t_start

    # Interpolation fractions at overlap boundaries
    a_dur = a_seg.t_end - a_seg.t_start
    b_dur = b_seg.t_end - b_seg.t_start

    aa0 = (t_start - a_seg.t_start) / a_dur if a_dur > 0 else 0.0
    aa1 = (t_end - a_seg.t_start) / a_dur if a_dur > 0 else 0.0
    ab0 = (t_start - b_seg.t_start) / b_dur if b_dur > 0 else 0.0
    ab1 = (t_end - b_seg.t_start) / b_dur if b_dur > 0 else 0.0

    # Positions at overlap start (u=0) and end (u=1)
    ax0 = a_seg.start.x + aa0 * (a_seg.end.x - a_seg.start.x)
    ay0 = a_seg.start.y + aa0 * (a_seg.end.y - a_seg.start.y)
    bx0 = b_seg.start.x + ab0 * (b_seg.end.x - b_seg.start.x)
    by0 = b_seg.start.y + ab0 * (b_seg.end.y - b_seg.start.y)

    ax1 = a_seg.start.x + aa1 * (a_seg.end.x - a_seg.start.x)
    ay1 = a_seg.start.y + aa1 * (a_seg.end.y - a_seg.start.y)
    bx1 = b_seg.start.x + ab1 * (b_seg.end.x - b_seg.start.x)
    by1 = b_seg.start.y + ab1 * (b_seg.end.y - b_seg.start.y)

    # diff(u) = A(u) - B(u),  u in [0, 1]
    dx0, dy0 = ax0 - bx0, ay0 - by0
    dx1, dy1 = ax1 - bx1, ay1 - by1
    ddx, ddy = dx1 - dx0, dy1 - dy0

    # dist^2(u) = (dx0 + u*ddx)^2 + (dy0 + u*ddy)^2
    # Minimise:  u* = -(dx0*ddx + dy0*ddy) / (ddx^2 + ddy^2)
    denom = ddx * ddx + ddy * ddy
    if denom > 1e-12:
        u_min = -(dx0 * ddx + dy0 * ddy) / denom
        u_min = max(0.0, min(1.0, u_min))
    else:
        u_min = 0.0  # constant distance throughout overlap

    # Evaluate at analytical minimum and both endpoints
    best_u = u_min
    dx = dx0 + best_u * ddx
    dy = dy0 + best_u * ddy
    best_dist = math.sqrt(dx * dx + dy * dy)

    for u in (0.0, 1.0):
        dx = dx0 + u * ddx
        dy = dy0 + u * ddy
        d = math.sqrt(dx * dx + dy * dy)
        if d < best_dist:
            best_dist = d
            best_u = u

    best_t = t_start + best_u * overlap_dur
    return best_dist, best_t


# ---------------------------------------------------------------------------
# Conflict classification
# ---------------------------------------------------------------------------

def _classify_conflict(
    a_seg: TimedSegment,
    b_seg: TimedSegment,
    threshold: float,
) -> ConflictType:
    """Classify a detected proximity violation by segment geometry."""
    # Edge swap: A goes P1->P2 while B goes P2->P1
    if (_dist(a_seg.start, b_seg.end) < threshold
            and _dist(a_seg.end, b_seg.start) < threshold):
        return ConflictType.EDGE_SWAP

    # Vertex: both converge on / depart from the same point
    if (_dist(a_seg.end, b_seg.end) < threshold
            or _dist(a_seg.start, b_seg.start) < threshold):
        return ConflictType.VERTEX

    return ConflictType.PROXIMITY


# ---------------------------------------------------------------------------
# Timing model
# ---------------------------------------------------------------------------

def build_timed_path(
    state: AMRState,
    intent: MovementIntent,
    config: ConflictDetectionConfig,
) -> list[TimedSegment]:
    """
    Convert an AMR's current state + movement intent into an ordered
    list of time-stamped straight-line segments.

    Returns an empty list when there are no meaningful segments
    (empty path, all waypoints identical, etc.).
    """
    # Full waypoint list: current position -> path waypoints
    waypoints: list[Position] = [state.position] + list(intent.path)

    # Remove consecutive duplicate waypoints
    deduped: list[Position] = [waypoints[0]]
    for wp in waypoints[1:]:
        if wp.x != deduped[-1].x or wp.y != deduped[-1].y:
            deduped.append(wp)

    if len(deduped) < 2:
        return []

    # Per-segment lengths and raw durations
    speed = state.velocity if state.velocity > 0 else config.default_speed

    raw: list[tuple[Position, Position, float]] = []  # (start, end, duration)
    for i in range(len(deduped) - 1):
        p1, p2 = deduped[i], deduped[i + 1]
        length = _dist(p1, p2)
        duration = length / speed
        raw.append((p1, p2, duration))

    total_raw = sum(d for _, _, d in raw)

    # Scale to match ETA when provided
    if intent.eta is not None and intent.eta > 0 and total_raw > 0:
        scale = intent.eta / total_raw
        raw = [(p1, p2, dur * scale) for p1, p2, dur in raw]

    # Build TimedSegments with cumulative timestamps
    t = state.timestamp
    result: list[TimedSegment] = []
    for p1, p2, duration in raw:
        if duration > 0:
            result.append(TimedSegment(start=p1, end=p2, t_start=t, t_end=t + duration))
        t += duration

    return result


# ---------------------------------------------------------------------------
# Pairwise conflict detection
# ---------------------------------------------------------------------------

def detect_pairwise_conflicts(
    a_id: str,
    a_state: AMRState,
    a_intent: MovementIntent | None,
    b_id: str,
    b_state: AMRState,
    b_intent: MovementIntent | None,
    config: ConflictDetectionConfig,
) -> list[ConflictResult]:
    """
    Detect all spatio-temporal conflicts between two robots.

    Returns an empty list when:

    - same robot (``a_id == b_id``)
    - either intent is ``None``
    - no path segments or no temporal overlap

    Results are sorted deterministically by
    ``(time_window_start, robot_a_id, robot_b_id, conflict_type)``.
    """
    if a_id == b_id:
        return []
    if a_intent is None or b_intent is None:
        return []

    # Normalise pair ordering for deterministic results
    if a_id > b_id:
        a_id, a_state, a_intent, b_id, b_state, b_intent = (
            b_id, b_state, b_intent, a_id, a_state, a_intent,
        )

    a_path = build_timed_path(a_state, a_intent, config)
    b_path = build_timed_path(b_state, b_intent, config)

    if not a_path or not b_path:
        return []

    conflicts: list[ConflictResult] = []

    for a_seg in a_path:
        for b_seg in b_path:
            # Temporal overlap
            t_start = max(a_seg.t_start, b_seg.t_start)
            t_end = min(a_seg.t_end, b_seg.t_end)

            if (t_end - t_start) < config.temporal_threshold:
                continue

            # Minimum distance during overlap (analytical)
            min_dist, min_t = _min_distance_during_overlap(
                a_seg, b_seg, t_start, t_end,
            )

            if min_dist >= config.spatial_threshold:
                continue

            # Classify and record
            conflict_type = _classify_conflict(
                a_seg, b_seg, config.spatial_threshold,
            )

            # Location: midpoint between the two robots at min-distance time
            a_pos = _position_at_time(a_seg, min_t)
            b_pos = _position_at_time(b_seg, min_t)
            location = Position(
                x=(a_pos.x + b_pos.x) / 2.0,
                y=(a_pos.y + b_pos.y) / 2.0,
            )

            conflicts.append(ConflictResult(
                robot_a_id=a_id,
                robot_b_id=b_id,
                conflict_type=conflict_type,
                location=location,
                time_window_start=t_start,
                time_window_end=t_end,
                min_distance=min_dist,
                robot_a_path_version=a_intent.path_version,
                robot_b_path_version=b_intent.path_version,
            ))

    conflicts.sort(key=lambda c: (
        c.time_window_start, c.robot_a_id, c.robot_b_id, c.conflict_type.value,
    ))
    return conflicts


# ---------------------------------------------------------------------------
# Multi-robot detection
# ---------------------------------------------------------------------------

def detect_all_conflicts(
    peers: dict[str, AMRState],
    intents: dict[str, MovementIntent],
    config: ConflictDetectionConfig | None = None,
) -> list[ConflictResult]:
    """
    Evaluate all pairwise conflicts among robots that have both a known
    state and a movement intent.

    Skips self-pairs.  Avoids duplicate pair evaluation.
    Results sorted deterministically.
    """
    if config is None:
        config = ConflictDetectionConfig()

    # Robots that have both state and intent
    active_ids = sorted(set(peers.keys()) & set(intents.keys()))

    all_conflicts: list[ConflictResult] = []
    for i in range(len(active_ids)):
        for j in range(i + 1, len(active_ids)):
            a_id, b_id = active_ids[i], active_ids[j]
            pairwise = detect_pairwise_conflicts(
                a_id, peers[a_id], intents[a_id],
                b_id, peers[b_id], intents[b_id],
                config,
            )
            all_conflicts.extend(pairwise)

    all_conflicts.sort(key=lambda c: (
        c.time_window_start, c.robot_a_id, c.robot_b_id, c.conflict_type.value,
    ))
    return all_conflicts
