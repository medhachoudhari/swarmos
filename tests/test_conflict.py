"""
Unit tests for spatio-temporal conflict detection.

All scenarios use realistic warehouse coordinates:
  - Warehouse grid roughly (0,0) to (20,15) metres
  - Aisles at y=5, y=10
  - Cross-aisles at x=5, x=10, x=15
  - Robot speed typically 1.0 m/s
  - spatial_threshold = 1.5 m  (~1 m robot diameter + 0.5 m margin)

No randomness.  All timing is explicit.
"""

from __future__ import annotations

import math

import pytest

from app.coordination.models import AMRState, MovementIntent, Position, RobotStatus
from app.coordination.conflict import (
    ConflictDetectionConfig,
    ConflictResult,
    ConflictType,
    TimedSegment,
    build_timed_path,
    detect_all_conflicts,
    detect_pairwise_conflicts,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _pos(x: float, y: float) -> Position:
    return Position(x=x, y=y)


def _state(
    rid: str,
    x: float,
    y: float,
    t: float = 0.0,
    v: float = 1.0,
) -> AMRState:
    return AMRState(
        robot_id=rid,
        timestamp=t,
        position=_pos(x, y),
        velocity=v,
        heading=0.0,
        status=RobotStatus.MOVING,
        battery=80.0,
    )


def _intent(
    target: Position,
    path: list[Position],
    eta: float | None = None,
    path_version: int = 1,
    intent_id: str = "i-1",
) -> MovementIntent:
    return MovementIntent(
        target=target,
        path=path,
        eta=eta,
        intent_id=intent_id,
        path_version=path_version,
    )


CFG = ConflictDetectionConfig(
    spatial_threshold=1.5,
    temporal_threshold=0.5,
    default_speed=1.0,
)


# =========================================================================
# TIMING MODEL TESTS
# =========================================================================


class TestTimingModel:
    """Verify the deterministic timing model."""

    def test_speed_based_timing(self):
        """10 m at 2 m/s => 5 s segment."""
        st = _state("r1", 0, 0, t=0.0, v=2.0)
        intent = _intent(_pos(10, 0), [_pos(10, 0)])
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) == 1
        assert math.isclose(segs[0].t_end - segs[0].t_start, 5.0)

    def test_eta_constrains_arrival(self):
        """ETA=20 s overrides speed-based 5 s."""
        st = _state("r1", 0, 0, t=0.0, v=2.0)
        intent = _intent(_pos(10, 0), [_pos(10, 0)], eta=20.0)
        segs = build_timed_path(st, intent, CFG)
        assert math.isclose(segs[0].t_end - segs[0].t_start, 20.0)

    def test_eta_none_uses_speed(self):
        """ETA=None falls back to speed-based estimate."""
        st = _state("r1", 0, 0, t=0.0, v=5.0)
        intent = _intent(_pos(10, 0), [_pos(10, 0)], eta=None)
        segs = build_timed_path(st, intent, CFG)
        assert math.isclose(segs[0].t_end - segs[0].t_start, 2.0)

    def test_zero_velocity_uses_default_speed(self):
        """velocity=0 => default_speed=1.0 m/s => 10 s for 10 m."""
        st = _state("r1", 0, 0, t=0.0, v=0.0)
        intent = _intent(_pos(10, 0), [_pos(10, 0)])
        segs = build_timed_path(st, intent, CFG)
        assert math.isclose(segs[0].t_end - segs[0].t_start, 10.0)

    def test_deterministic_timing(self):
        """Same input => same output, every time."""
        st = _state("r1", 0, 0, t=100.0, v=1.0)
        intent = _intent(_pos(5, 0), [_pos(5, 0)], eta=10.0)
        s1 = build_timed_path(st, intent, CFG)
        s2 = build_timed_path(st, intent, CFG)
        assert s1[0].t_start == s2[0].t_start
        assert s1[0].t_end == s2[0].t_end

    def test_multi_segment_timing(self):
        """Two consecutive 5 m segments at 1 m/s => 5 + 5 s."""
        st = _state("r1", 0, 0, t=0.0, v=1.0)
        intent = _intent(_pos(10, 0), [_pos(5, 0), _pos(10, 0)])
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) == 2
        assert math.isclose(segs[0].t_end, 5.0)
        assert math.isclose(segs[1].t_end, 10.0)

    def test_eta_scales_multi_segment(self):
        """ETA=20 s for two equal 5 m segments => each gets 10 s."""
        st = _state("r1", 0, 0, t=0.0, v=1.0)
        intent = _intent(_pos(10, 0), [_pos(5, 0), _pos(10, 0)], eta=20.0)
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) == 2
        assert math.isclose(segs[0].t_end - segs[0].t_start, 10.0)
        assert math.isclose(segs[1].t_end - segs[1].t_start, 10.0)


# =========================================================================
# CONFLICT DETECTION CORE
# =========================================================================


class TestConflictDetection:
    """Core conflict detection scenarios."""

    def test_vertex_conflict_detected(self):
        """Two robots approaching the same intersection from perpendicular aisles."""
        # R1: (5,5) -> (10,5) along east aisle, 5m at 1m/s => t=[0,5]
        # R2: (10,0) -> (10,5) along north cross-aisle, 5m at 1m/s => t=[0,5]
        # Both arrive at (10,5) at t=5 => VERTEX conflict
        r1s = _state("r1", 5, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 10, 0, t=0.0, v=1.0)
        r2i = _intent(_pos(10, 5), [_pos(10, 5)])

        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == ConflictType.VERTEX for c in conflicts)

    def test_edge_swap_conflict_detected(self):
        """Two robots entering the same aisle from opposite ends."""
        # R1: (0,5) -> (10,5)  east
        # R2: (10,5) -> (0,5)  west    => EDGE_SWAP
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 10, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(0, 5), [_pos(0, 5)])

        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == ConflictType.EDGE_SWAP for c in conflicts)

    def test_proximity_conflict_detected(self):
        """Paths cross at a shallow angle — close mid-segment but endpoints far apart.

        R1: (0,5)  -> (20,5)   straight east along aisle y=5
        R2: (0,8)  -> (20,2)   diagonal cutting across, closest approach
             near the midpoint at y~5, x~10.
        Endpoints are well-separated (> 1.5 m) so it is not VERTEX.
        Segments are not swapped so it is not EDGE_SWAP.
        """
        r1s = _state("r1", 0, 5.0, t=0.0, v=1.0)
        r1i = _intent(_pos(20, 5.0), [_pos(20, 5.0)])
        r2s = _state("r2", 0, 8.0, t=0.0, v=1.0)
        r2i = _intent(_pos(20, 2.0), [_pos(20, 2.0)])

        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == ConflictType.PROXIMITY for c in conflicts)

    def test_temporally_separated_no_conflict(self):
        """Same path but 100 s apart => no temporal overlap => no conflict."""
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 0, 5, t=100.0, v=1.0)
        r2i = _intent(_pos(10, 5), [_pos(10, 5)])

        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(conflicts) == 0

    def test_spatially_overlapping_but_time_disjoint(self):
        """Paths overlap spatially, but one finishes before the other starts."""
        r1s = _state("r1", 0, 5, t=0.0, v=10.0)  # done at t=1
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 10, 5, t=100.0, v=1.0)  # starts at t=100
        r2i = _intent(_pos(0, 5), [_pos(0, 5)])

        assert len(detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)) == 0

    def test_clearly_separate_paths_no_conflict(self):
        """Robots in completely different warehouse zones."""
        r1s = _state("r1", 0, 0, t=0.0, v=1.0)
        r1i = _intent(_pos(5, 0), [_pos(5, 0)])
        r2s = _state("r2", 100, 100, t=0.0, v=1.0)
        r2i = _intent(_pos(105, 100), [_pos(105, 100)])

        assert len(detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)) == 0

    def test_self_conflict_not_reported(self):
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        assert len(detect_pairwise_conflicts("r1", r1s, r1i, "r1", r1s, r1i, CFG)) == 0

    def test_none_intent_no_conflict(self):
        r1s = _state("r1", 0, 0, t=0.0)
        r2s = _state("r2", 1, 0, t=0.0)
        r2i = _intent(_pos(10, 0), [_pos(10, 0)])
        assert len(detect_pairwise_conflicts("r1", r1s, None, "r2", r2s, r2i, CFG)) == 0

    def test_empty_path_handled(self):
        """Empty path (robot at target) => no segments => no crash."""
        r1s = _state("r1", 10, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [])  # already there
        r2s = _state("r2", 10, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(15, 5), [_pos(15, 5)])
        result = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert isinstance(result, list)  # no crash

    def test_one_waypoint_path(self):
        st = _state("r1", 0, 0, t=0.0, v=1.0)
        intent = _intent(_pos(5, 0), [_pos(5, 0)])
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) == 1

    def test_zero_length_segment_no_crash(self):
        """Duplicate consecutive waypoints deduplicated gracefully."""
        st = _state("r1", 5, 5, t=0.0, v=1.0)
        intent = _intent(_pos(10, 5), [_pos(5, 5), _pos(5, 5), _pos(10, 5)])
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) >= 1

    def test_all_identical_waypoints_no_segments(self):
        st = _state("r1", 0, 0, t=0.0, v=1.0)
        intent = _intent(_pos(0, 0), [_pos(0, 0)])
        segs = build_timed_path(st, intent, CFG)
        assert len(segs) == 0

    def test_one_way_no_false_edge_swap(self):
        """R1 and R2 travel same direction => should NOT be EDGE_SWAP."""
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 0.5, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(10, 5), [_pos(10, 5)])

        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        for c in conflicts:
            assert c.conflict_type != ConflictType.EDGE_SWAP


# =========================================================================
# CONFLICT RESULT STRUCTURE
# =========================================================================


class TestConflictResultFields:
    """Verify that ConflictResult carries all required fields."""

    @pytest.fixture()
    def _edge_swap_conflicts(self):
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)], path_version=3)
        r2s = _state("r2", 10, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(0, 5), [_pos(0, 5)], path_version=7)
        return detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)

    def test_result_contains_robot_ids(self, _edge_swap_conflicts):
        c = _edge_swap_conflicts[0]
        assert c.robot_a_id == "r1"
        assert c.robot_b_id == "r2"

    def test_result_contains_type(self, _edge_swap_conflicts):
        assert _edge_swap_conflicts[0].conflict_type in ConflictType

    def test_result_contains_time_window(self, _edge_swap_conflicts):
        c = _edge_swap_conflicts[0]
        assert c.time_window_start <= c.time_window_end

    def test_result_contains_path_versions(self, _edge_swap_conflicts):
        c = _edge_swap_conflicts[0]
        assert c.robot_a_path_version == 3
        assert c.robot_b_path_version == 7

    def test_result_contains_location(self, _edge_swap_conflicts):
        c = _edge_swap_conflicts[0]
        assert hasattr(c.location, "x")
        assert hasattr(c.location, "y")

    def test_result_contains_min_distance(self, _edge_swap_conflicts):
        c = _edge_swap_conflicts[0]
        assert c.min_distance >= 0.0

    def test_identical_input_produces_identical_result(self):
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 10, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(0, 5), [_pos(0, 5)])
        c1 = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        c2 = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.robot_a_id == b.robot_a_id
            assert a.robot_b_id == b.robot_b_id
            assert a.conflict_type == b.conflict_type
            assert a.time_window_start == b.time_window_start
            assert a.min_distance == b.min_distance

    def test_conflict_result_serializable(self):
        """ConflictResult round-trips through JSON."""
        r1s = _state("r1", 0, 5, t=0.0, v=1.0)
        r1i = _intent(_pos(10, 5), [_pos(10, 5)])
        r2s = _state("r2", 10, 5, t=0.0, v=1.0)
        r2i = _intent(_pos(0, 5), [_pos(0, 5)])
        conflicts = detect_pairwise_conflicts("r1", r1s, r1i, "r2", r2s, r2i, CFG)
        assert len(conflicts) >= 1
        json_str = conflicts[0].model_dump_json()
        reconstructed = ConflictResult.model_validate_json(json_str)
        assert reconstructed.robot_a_id == conflicts[0].robot_a_id
        assert reconstructed.conflict_type == conflicts[0].conflict_type


# =========================================================================
# MULTI-ROBOT SCENARIOS
# =========================================================================


class TestMultiRobot:
    """Fleet-level conflict detection."""

    def test_three_robot_selective_conflict(self):
        """R1/R2 conflict in same aisle, R3 far away => only R1-R2 conflict."""
        peers = {
            "r1": _state("r1", 0, 5, t=0.0, v=1.0),
            "r2": _state("r2", 10, 5, t=0.0, v=1.0),
            "r3": _state("r3", 100, 100, t=0.0, v=1.0),
        }
        intents = {
            "r1": _intent(_pos(10, 5), [_pos(10, 5)]),
            "r2": _intent(_pos(0, 5), [_pos(0, 5)]),
            "r3": _intent(_pos(105, 100), [_pos(105, 100)]),
        }
        conflicts = detect_all_conflicts(peers, intents, CFG)
        assert len(conflicts) >= 1
        assert all(
            c.robot_a_id in ("r1", "r2") and c.robot_b_id in ("r1", "r2")
            for c in conflicts
        )

    def test_no_duplicate_pairs(self):
        """Pair (A,B) always normalised so robot_a_id < robot_b_id."""
        peers = {
            "r1": _state("r1", 0, 5, t=0.0, v=1.0),
            "r2": _state("r2", 10, 5, t=0.0, v=1.0),
        }
        intents = {
            "r1": _intent(_pos(10, 5), [_pos(10, 5)]),
            "r2": _intent(_pos(0, 5), [_pos(0, 5)]),
        }
        conflicts = detect_all_conflicts(peers, intents, CFG)
        for c in conflicts:
            assert c.robot_a_id < c.robot_b_id

    def test_multi_robot_ordering_deterministic(self):
        peers = {
            "r1": _state("r1", 0, 5, t=0.0, v=1.0),
            "r2": _state("r2", 10, 5, t=0.0, v=1.0),
            "r3": _state("r3", 0, 5.5, t=0.0, v=1.0),
        }
        intents = {
            "r1": _intent(_pos(10, 5), [_pos(10, 5)]),
            "r2": _intent(_pos(0, 5), [_pos(0, 5)]),
            "r3": _intent(_pos(10, 5.5), [_pos(10, 5.5)]),
        }
        c1 = detect_all_conflicts(peers, intents, CFG)
        c2 = detect_all_conflicts(peers, intents, CFG)
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.robot_a_id == b.robot_a_id
            assert a.robot_b_id == b.robot_b_id

    def test_five_robot_fleet_runs(self):
        """5-robot fleet runs without errors and is deterministic."""
        peers = {}
        intents = {}
        for i in range(5):
            rid = f"r{i + 1:02d}"
            peers[rid] = _state(rid, x=i * 5, y=0, t=0.0, v=1.0)
            intents[rid] = _intent(
                _pos(i * 5 + 10, 0),
                [_pos(i * 5 + 5, 0), _pos(i * 5 + 10, 0)],
                intent_id=f"i-{rid}",
            )
        c1 = detect_all_conflicts(peers, intents, CFG)
        c2 = detect_all_conflicts(peers, intents, CFG)
        assert isinstance(c1, list)
        assert len(c1) == len(c2)

    def test_five_robot_separate_aisles_no_conflicts(self):
        """5 robots in well-separated parallel aisles => zero conflicts."""
        peers = {}
        intents = {}
        for i in range(5):
            rid = f"r{i + 1:02d}"
            y = i * 10.0  # 10 m separation per aisle
            peers[rid] = _state(rid, x=0, y=y, t=0.0, v=1.0)
            intents[rid] = _intent(
                _pos(20, y),
                [_pos(10, y), _pos(20, y)],
                intent_id=f"i-{rid}",
            )
        assert len(detect_all_conflicts(peers, intents, CFG)) == 0

    def test_robot_without_intent_excluded(self):
        """Robot with state but no intent doesn't participate."""
        peers = {
            "r1": _state("r1", 0, 5, t=0.0),
            "r2": _state("r2", 10, 5, t=0.0),
        }
        intents = {
            "r1": _intent(_pos(10, 5), [_pos(10, 5)]),
            # r2 has no intent
        }
        assert len(detect_all_conflicts(peers, intents, CFG)) == 0
