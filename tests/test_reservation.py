"""
Unit tests for the spatio-temporal corridor reservation engine (Step 3).

All tests use explicit timestamps and deterministic inputs — no
``time.time()`` calls, no randomness, no networking.

Warehouse resource IDs follow the convention:
- ``corridor-<name>``   (aisle segment)
- ``intersection-<x>-<y>``  (grid junction)
- ``staging-<id>``      (staging area)
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.coordination.reservation import (
    Reservation,
    ReservationConflictInfo,
    ReservationManager,
    ReservationRequest,
    ReservationResult,
    ReservationStatus,
    is_valid_transition,
    _intervals_overlap,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _req(
    reservation_id: str = "res-1",
    robot_id: str = "amr-01",
    resource_id: str = "corridor-A1",
    start_time: float = 10.0,
    end_time: float = 20.0,
    path_version: int = 1,
    created_at: float = 0.0,
    source_conflict_id: str | None = None,
) -> ReservationRequest:
    return ReservationRequest(
        reservation_id=reservation_id,
        robot_id=robot_id,
        resource_id=resource_id,
        start_time=start_time,
        end_time=end_time,
        path_version=path_version,
        created_at=created_at,
        source_conflict_id=source_conflict_id,
    )


# =========================================================================
# 1. MODEL VALIDATION
# =========================================================================


class TestReservationModel:
    """Tests 1–7: Reservation / ReservationRequest model validation."""

    def test_valid_reservation_accepted(self):
        """1. A fully valid reservation is constructed without error."""
        r = Reservation(
            reservation_id="res-1",
            robot_id="amr-01",
            resource_id="corridor-A1",
            start_time=10.0,
            end_time=20.0,
            path_version=1,
            status=ReservationStatus.CONFIRMED,
            created_at=0.0,
        )
        assert r.reservation_id == "res-1"
        assert r.status == ReservationStatus.CONFIRMED

    def test_invalid_start_end_ordering_rejected(self):
        """2. start_time >= end_time rejected."""
        with pytest.raises(ValidationError):
            Reservation(
                reservation_id="res-1",
                robot_id="amr-01",
                resource_id="corridor-A1",
                start_time=20.0,
                end_time=10.0,
                path_version=1,
                created_at=0.0,
            )
        # Equal times also invalid
        with pytest.raises(ValidationError):
            Reservation(
                reservation_id="res-1",
                robot_id="amr-01",
                resource_id="corridor-A1",
                start_time=10.0,
                end_time=10.0,
                path_version=1,
                created_at=0.0,
            )

    def test_negative_times_rejected(self):
        """3. Negative start_time or end_time rejected."""
        with pytest.raises(ValidationError):
            _req(start_time=-1.0)
        with pytest.raises(ValidationError):
            _req(end_time=-5.0)

    def test_non_finite_times_rejected(self):
        """4. NaN / Inf times rejected."""
        with pytest.raises(ValidationError):
            _req(start_time=float("nan"))
        with pytest.raises(ValidationError):
            _req(end_time=float("inf"))
        with pytest.raises(ValidationError):
            _req(start_time=float("-inf"))

    def test_empty_whitespace_ids_rejected(self):
        """5. Empty or whitespace-only IDs rejected."""
        with pytest.raises(ValidationError):
            _req(reservation_id="")
        with pytest.raises(ValidationError):
            _req(robot_id="   ")
        with pytest.raises(ValidationError):
            _req(resource_id="")
        with pytest.raises(ValidationError):
            _req(reservation_id="  \t  ")

    def test_path_version_validation(self):
        """6. path_version must be >= 1."""
        with pytest.raises(ValidationError):
            _req(path_version=0)
        with pytest.raises(ValidationError):
            _req(path_version=-1)
        # Valid
        r = _req(path_version=1)
        assert r.path_version == 1

    def test_invalid_status_transitions_rejected(self):
        """7. State machine rejects illegal transitions."""
        # Terminal states have no outbound transitions
        assert is_valid_transition(
            ReservationStatus.RELEASED, ReservationStatus.CONFIRMED,
        ) is False
        assert is_valid_transition(
            ReservationStatus.EXPIRED, ReservationStatus.CONFIRMED,
        ) is False
        assert is_valid_transition(
            ReservationStatus.REJECTED, ReservationStatus.CONFIRMED,
        ) is False
        # CONFIRMED cannot go back to REQUESTED
        assert is_valid_transition(
            ReservationStatus.CONFIRMED, ReservationStatus.REQUESTED,
        ) is False

        # Valid transitions
        assert is_valid_transition(
            ReservationStatus.REQUESTED, ReservationStatus.CONFIRMED,
        ) is True
        assert is_valid_transition(
            ReservationStatus.REQUESTED, ReservationStatus.REJECTED,
        ) is True
        assert is_valid_transition(
            ReservationStatus.CONFIRMED, ReservationStatus.RELEASED,
        ) is True
        assert is_valid_transition(
            ReservationStatus.CONFIRMED, ReservationStatus.EXPIRED,
        ) is True
        assert is_valid_transition(
            ReservationStatus.CONFIRMED, ReservationStatus.INVALIDATED,
        ) is True


# =========================================================================
# 2. BASIC RESERVATION OPERATIONS
# =========================================================================


class TestBasicReservation:
    """Tests 8–13: Core request / confirm / reject / query."""

    def test_free_resource_confirms(self):
        """8. Requesting a free resource succeeds."""
        mgr = ReservationManager()
        result = mgr.request_reservation(_req())
        assert result.success is True
        assert len(result.reservations) == 1
        assert result.reservations[0].status == ReservationStatus.CONFIRMED

    def test_overlapping_reservation_rejects(self):
        """9. Two overlapping reservations on the same resource conflict."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
            start_time=10.0, end_time=20.0,
        ))
        result = mgr.request_reservation(_req(
            reservation_id="res-2", robot_id="amr-02",
            start_time=15.0, end_time=25.0,
        ))
        assert result.success is False
        assert len(result.conflicts) >= 1

    def test_different_resources_can_overlap(self):
        """10. Same time interval on different resources → no conflict."""
        mgr = ReservationManager()
        r1 = mgr.request_reservation(_req(
            reservation_id="res-1", resource_id="corridor-A1",
        ))
        r2 = mgr.request_reservation(_req(
            reservation_id="res-2", resource_id="corridor-B2",
        ))
        assert r1.success is True
        assert r2.success is True

    def test_same_resource_non_overlapping_succeeds(self):
        """11. Same resource at non-overlapping times → both succeed."""
        mgr = ReservationManager()
        r1 = mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=15.0,
        ))
        r2 = mgr.request_reservation(_req(
            reservation_id="res-2", robot_id="amr-02",
            start_time=15.0, end_time=20.0,
        ))
        assert r1.success is True
        assert r2.success is True

    def test_touching_boundary_no_overlap(self):
        """12. [10,13) and [13,16) do NOT overlap (half-open interval)."""
        assert _intervals_overlap(10, 13, 13, 16) is False
        # But [10,13) and [12,16) DO overlap
        assert _intervals_overlap(10, 13, 12, 16) is True

        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=13.0,
        ))
        # Touching boundary → should succeed
        result = mgr.request_reservation(_req(
            reservation_id="res-2", robot_id="amr-02",
            start_time=13.0, end_time=16.0,
        ))
        assert result.success is True

    def test_reservation_query_works(self):
        """13. get_reservation returns correct data."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(reservation_id="res-1"))
        r = mgr.get_reservation("res-1")
        assert r is not None
        assert r.reservation_id == "res-1"
        assert r.status == ReservationStatus.CONFIRMED
        # Non-existent returns None
        assert mgr.get_reservation("res-999") is None


# =========================================================================
# 3. IDEMPOTENCY
# =========================================================================


class TestIdempotency:
    """Tests 14–15: Duplicate request handling."""

    def test_duplicate_reservation_id_no_duplicate_lock(self):
        """14. Same reservation_id + same content → no duplicate, returns existing."""
        mgr = ReservationManager()
        req = _req(reservation_id="res-idem")
        r1 = mgr.request_reservation(req)
        r2 = mgr.request_reservation(req)
        assert r1.success is True
        assert r2.success is True
        assert len(r2.reservations) == 1
        assert r2.reservations[0].reservation_id == "res-idem"
        # Only one reservation in the system
        all_r = mgr.get_robot_reservations("amr-01")
        idem_count = sum(
            1 for r in all_r if r.reservation_id == "res-idem"
        )
        assert idem_count == 1

    def test_same_id_different_content_rejected(self):
        """15. Same reservation_id with different content is rejected."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=20.0,
        ))
        result = mgr.request_reservation(_req(
            reservation_id="res-1", start_time=30.0, end_time=40.0,
        ))
        assert result.success is False


# =========================================================================
# 4. PATH VERSION BINDING
# =========================================================================


class TestPathVersion:
    """Tests 16–19: Path version semantics."""

    def test_current_path_reservation_accepted(self):
        """16. Reservation with valid path_version succeeds."""
        mgr = ReservationManager()
        result = mgr.request_reservation(_req(path_version=3))
        assert result.success is True
        assert result.reservations[0].path_version == 3

    def test_stale_path_cannot_overwrite_newer(self):
        """17. Older path version reservation cannot steal newer's resource."""
        mgr = ReservationManager()
        # Robot 01 reserves with path_version=3
        mgr.request_reservation(_req(
            reservation_id="res-new", robot_id="amr-01",
            path_version=3, start_time=10.0, end_time=20.0,
        ))
        # Robot 02 tries the same resource (different robot, so it's a conflict)
        result = mgr.request_reservation(_req(
            reservation_id="res-old", robot_id="amr-02",
            path_version=1, start_time=10.0, end_time=20.0,
        ))
        assert result.success is False

    def test_invalidate_old_path_reservations(self):
        """18. invalidate_robot_path invalidates correct path version."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-v2", path_version=2,
        ))
        mgr.request_reservation(_req(
            reservation_id="res-v3", path_version=3,
            resource_id="corridor-B1",
        ))
        count = mgr.invalidate_robot_path("amr-01", path_version=2)
        assert count == 1
        r2 = mgr.get_reservation("res-v2")
        assert r2.status == ReservationStatus.INVALIDATED
        r3 = mgr.get_reservation("res-v3")
        assert r3.status == ReservationStatus.CONFIRMED

    def test_new_path_reserves_after_old_invalidated(self):
        """19. After invalidating old path, new path can reserve the resource."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-old", path_version=2,
        ))
        mgr.invalidate_robot_path("amr-01", path_version=2)
        result = mgr.request_reservation(_req(
            reservation_id="res-new", path_version=3,
        ))
        assert result.success is True


# =========================================================================
# 5. EXPIRATION
# =========================================================================


class TestExpiration:
    """Tests 20–23: Time-based expiration with explicit current_time."""

    def test_reservation_active_before_end(self):
        """20. Reservation remains active before end_time."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(start_time=10.0, end_time=20.0))
        expired_count = mgr.expire(current_time=15.0)
        assert expired_count == 0
        r = mgr.get_reservation("res-1")
        assert r.status == ReservationStatus.CONFIRMED

    def test_reservation_expires_at_boundary(self):
        """21. end_time <= current_time triggers expiration."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(start_time=10.0, end_time=20.0))
        expired_count = mgr.expire(current_time=20.0)
        assert expired_count == 1
        r = mgr.get_reservation("res-1")
        assert r.status == ReservationStatus.EXPIRED

    def test_expired_reservation_does_not_block(self):
        """22. Expired reservation no longer blocks future reservations."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-old", start_time=10.0, end_time=20.0,
        ))
        mgr.expire(current_time=25.0)
        # New reservation on same resource and overlapping time
        result = mgr.request_reservation(_req(
            reservation_id="res-new", robot_id="amr-02",
            start_time=10.0, end_time=20.0,
        ))
        assert result.success is True

    def test_explicit_current_time_controls_expiration(self):
        """23. Expiration is controlled deterministically by current_time."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=20.0,
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", start_time=10.0, end_time=30.0,
            resource_id="corridor-B1",
        ))
        # Only res-1 expires at t=20
        count = mgr.expire(current_time=20.0)
        assert count == 1
        assert mgr.get_reservation("res-1").status == ReservationStatus.EXPIRED
        assert mgr.get_reservation("res-2").status == ReservationStatus.CONFIRMED
        # Both expire at t=30
        count = mgr.expire(current_time=30.0)
        assert count == 1
        assert mgr.get_reservation("res-2").status == ReservationStatus.EXPIRED


# =========================================================================
# 6. RELEASE / INVALIDATION
# =========================================================================


class TestReleaseInvalidation:
    """Tests 24–27: Release and invalidation operations."""

    def test_release_one_reservation(self):
        """24. release_reservation releases a single reservation."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(reservation_id="res-1"))
        assert mgr.release_reservation("res-1", "amr-01") is True
        assert mgr.get_reservation("res-1").status == ReservationStatus.RELEASED

    def test_release_all_robot_reservations(self):
        """25. release_robot_reservations releases all CONFIRMED for a robot."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", resource_id="corridor-B1",
        ))
        count = mgr.release_robot_reservations("amr-01")
        assert count == 2
        assert mgr.get_reservation("res-1").status == ReservationStatus.RELEASED
        assert mgr.get_reservation("res-2").status == ReservationStatus.RELEASED

    def test_invalidate_one_path_version(self):
        """26. invalidate_robot_path only affects the specified version."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-v1", path_version=1,
            resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-v2", path_version=2,
            resource_id="corridor-B1",
        ))
        count = mgr.invalidate_robot_path("amr-01", path_version=1)
        assert count == 1
        assert mgr.get_reservation("res-v1").status == ReservationStatus.INVALIDATED
        assert mgr.get_reservation("res-v2").status == ReservationStatus.CONFIRMED

    def test_invalidate_all_robot_reservations(self):
        """27. invalidate_all_robot_reservations invalidates all CONFIRMED."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", path_version=1,
            resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", path_version=2,
            resource_id="corridor-B1",
        ))
        count = mgr.invalidate_all_robot_reservations("amr-01")
        assert count == 2
        assert mgr.get_reservation("res-1").status == ReservationStatus.INVALIDATED
        assert mgr.get_reservation("res-2").status == ReservationStatus.INVALIDATED


# =========================================================================
# 7. RENEWAL / EXTENSION
# =========================================================================


class TestRenewal:
    """Tests 28–31: Reservation renewal / extension."""

    def test_valid_renewal_succeeds(self):
        """28. Extending a CONFIRMED reservation succeeds if no conflict."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=20.0,
        ))
        result = mgr.renew("res-1", "amr-01", new_end_time=30.0, current_time=15.0)
        assert result.success is True
        assert result.reservations[0].end_time == 30.0
        assert result.reservations[0].path_version == 1  # preserved

    def test_renewal_blocked_by_another_robot(self):
        """29. Cannot extend into another robot's confirmed reservation."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
            start_time=10.0, end_time=20.0,
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", robot_id="amr-02",
            start_time=20.0, end_time=30.0,
        ))
        result = mgr.renew("res-1", "amr-01", new_end_time=25.0, current_time=15.0)
        assert result.success is False
        assert len(result.conflicts) >= 1

    def test_invalid_renewal_rejected(self):
        """30. Various invalid renewal attempts are rejected."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=20.0,
        ))
        # Shorten (new_end <= current end)
        result = mgr.renew("res-1", "amr-01", new_end_time=15.0, current_time=12.0)
        assert result.success is False

        # Wrong robot
        result = mgr.renew("res-1", "amr-02", new_end_time=30.0, current_time=12.0)
        assert result.success is False

        # Non-existent
        result = mgr.renew("res-999", "amr-01", new_end_time=30.0, current_time=12.0)
        assert result.success is False

        # NaN end time
        result = mgr.renew("res-1", "amr-01", new_end_time=float("nan"), current_time=12.0)
        assert result.success is False

    def test_renewal_preserves_ownership(self):
        """31. Renewed reservation keeps robot_id and path_version."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
            path_version=5, start_time=10.0, end_time=20.0,
        ))
        result = mgr.renew("res-1", "amr-01", new_end_time=30.0, current_time=15.0)
        assert result.success is True
        r = result.reservations[0]
        assert r.robot_id == "amr-01"
        assert r.path_version == 5
        assert r.reservation_id == "res-1"


# =========================================================================
# 8. ATOMIC MULTI-RESOURCE
# =========================================================================


class TestMultiResource:
    """Tests 32–34: All-or-nothing multi-resource reservation."""

    def test_all_resources_confirm(self):
        """32. All requested resources confirm when no conflicts."""
        mgr = ReservationManager()
        reqs = [
            _req(reservation_id="res-A", resource_id="corridor-A1",
                 start_time=10.0, end_time=20.0),
            _req(reservation_id="res-B", resource_id="corridor-B1",
                 start_time=10.0, end_time=20.0),
            _req(reservation_id="res-C", resource_id="intersection-5-10",
                 start_time=10.0, end_time=20.0),
        ]
        result = mgr.request_multiple(reqs)
        assert result.success is True
        assert len(result.reservations) == 3
        assert all(
            r.status == ReservationStatus.CONFIRMED
            for r in result.reservations
        )

    def test_one_conflict_causes_none_committed(self):
        """33. One conflict → none confirmed (atomic rollback)."""
        mgr = ReservationManager()
        # Pre-reserve corridor-B1
        mgr.request_reservation(_req(
            reservation_id="res-existing", robot_id="amr-02",
            resource_id="corridor-B1", start_time=10.0, end_time=20.0,
        ))
        reqs = [
            _req(reservation_id="res-A", resource_id="corridor-A1",
                 start_time=10.0, end_time=20.0),
            _req(reservation_id="res-B", resource_id="corridor-B1",
                 start_time=15.0, end_time=25.0),  # conflicts!
            _req(reservation_id="res-C", resource_id="intersection-5-10",
                 start_time=10.0, end_time=20.0),
        ]
        result = mgr.request_multiple(reqs)
        assert result.success is False
        assert len(result.conflicts) >= 1
        # res-A should NOT be confirmed
        r_a = mgr.get_reservation("res-A")
        assert r_a is not None
        assert r_a.status == ReservationStatus.REJECTED

    def test_repeated_multi_resource_deterministic(self):
        """34. Repeated multi-resource request is deterministic."""
        mgr = ReservationManager()
        reqs = [
            _req(reservation_id="res-A", resource_id="corridor-A1"),
            _req(reservation_id="res-B", resource_id="corridor-B1"),
        ]
        r1 = mgr.request_multiple(reqs)
        # Second call with same IDs → idempotent
        r2 = mgr.request_multiple(reqs)
        assert r1.success == r2.success
        assert len(r1.reservations) == len(r2.reservations)


# =========================================================================
# 9. CONFLICT INFORMATION
# =========================================================================


class TestConflictInformation:
    """Tests 35–40: Structured conflict information on rejection."""

    @pytest.fixture()
    def conflict_result(self) -> ReservationResult:
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
            resource_id="intersection-5-10",
            start_time=10.0, end_time=20.0,
            path_version=3,
            source_conflict_id="conflict-x",
        ))
        return mgr.request_reservation(_req(
            reservation_id="res-2", robot_id="amr-02",
            resource_id="intersection-5-10",
            start_time=15.0, end_time=25.0,
            path_version=5,
            source_conflict_id="conflict-y",
        ))

    def test_conflicting_reservation_ids_returned(self, conflict_result):
        """35. Conflict info includes the blocking reservation ID."""
        assert conflict_result.success is False
        assert conflict_result.conflicts[0].conflicting_reservation_id == "res-1"

    def test_conflicting_robot_ids_returned(self, conflict_result):
        """36. Conflict info includes the blocking robot ID."""
        assert conflict_result.conflicts[0].conflicting_robot_id == "amr-01"

    def test_overlap_interval_returned(self, conflict_result):
        """37. Conflict info includes the overlap interval."""
        c = conflict_result.conflicts[0]
        assert c.overlap_start == 15.0
        assert c.overlap_end == 20.0

    def test_resource_identity_preserved(self, conflict_result):
        """38. Conflict info preserves resource_id."""
        assert conflict_result.conflicts[0].resource_id == "intersection-5-10"

    def test_path_versions_preserved(self, conflict_result):
        """39. Conflict info includes conflicting path_version."""
        assert conflict_result.conflicts[0].conflicting_path_version == 3

    def test_source_conflict_metadata(self, conflict_result):
        """40. Source conflict metadata preserved on the rejected reservation."""
        rejected = conflict_result.reservations[0]
        assert rejected.source_conflict_id == "conflict-y"


# =========================================================================
# 10. SCENARIO TESTS
# =========================================================================


class TestScenarios:
    """Tests 41–46: Realistic warehouse coordination scenarios."""

    def test_two_robots_one_intersection(self):
        """41. Two robots competing for one intersection."""
        mgr = ReservationManager()
        r1 = mgr.request_reservation(_req(
            reservation_id="res-r1", robot_id="amr-01",
            resource_id="intersection-10-5",
            start_time=0.0, end_time=5.0, path_version=1,
        ))
        r2 = mgr.request_reservation(_req(
            reservation_id="res-r2", robot_id="amr-02",
            resource_id="intersection-10-5",
            start_time=3.0, end_time=8.0, path_version=1,
        ))
        assert r1.success is True
        assert r2.success is False
        assert r2.conflicts[0].conflicting_robot_id == "amr-01"

    def test_three_robots_bottleneck(self):
        """42. Three robots approaching the same bottleneck corridor."""
        mgr = ReservationManager()
        results = []
        for i in range(3):
            rid = f"amr-{i+1:02d}"
            result = mgr.request_reservation(_req(
                reservation_id=f"res-{rid}",
                robot_id=rid,
                resource_id="corridor-narrow-1",
                start_time=10.0 + i * 2,  # staggered starts
                end_time=20.0 + i * 2,
                path_version=1,
            ))
            results.append(result)
        # First succeeds
        assert results[0].success is True
        # Second overlaps → fails
        assert results[1].success is False
        # Third overlaps with first → fails
        assert results[2].success is False

    def test_multiple_resources_one_path(self):
        """43. Robot reserving multiple corridor segments for one path."""
        mgr = ReservationManager()
        reqs = [
            _req(reservation_id="res-seg1", resource_id="corridor-A1",
                 start_time=0.0, end_time=5.0),
            _req(reservation_id="res-seg2", resource_id="corridor-A2",
                 start_time=5.0, end_time=10.0),
            _req(reservation_id="res-seg3", resource_id="corridor-A3",
                 start_time=10.0, end_time=15.0),
        ]
        result = mgr.request_multiple(reqs)
        assert result.success is True
        assert len(result.reservations) == 3

    def test_old_path_invalidated_new_route_reserved(self):
        """44. Robot replans: invalidate old path, reserve new route."""
        mgr = ReservationManager()
        # Old path reservations
        mgr.request_reservation(_req(
            reservation_id="res-old-1", resource_id="corridor-A1",
            path_version=2, start_time=0.0, end_time=10.0,
        ))
        mgr.request_reservation(_req(
            reservation_id="res-old-2", resource_id="corridor-A2",
            path_version=2, start_time=10.0, end_time=20.0,
        ))
        # Robot replans → invalidate version 2
        mgr.invalidate_robot_path("amr-01", path_version=2)
        assert mgr.get_reservation("res-old-1").status == ReservationStatus.INVALIDATED
        assert mgr.get_reservation("res-old-2").status == ReservationStatus.INVALIDATED
        # New path on version 3 — can reuse the same resources
        new_result = mgr.request_multiple([
            _req(reservation_id="res-new-1", resource_id="corridor-A1",
                 path_version=3, start_time=0.0, end_time=10.0),
            _req(reservation_id="res-new-2", resource_id="corridor-B1",
                 path_version=3, start_time=10.0, end_time=20.0),
        ])
        assert new_result.success is True

    def test_five_robot_congested_corridor(self):
        """45. Five-robot congested corridor — sequential time slotting."""
        mgr = ReservationManager()
        results = []
        for i in range(5):
            rid = f"amr-{i+1:02d}"
            result = mgr.request_reservation(_req(
                reservation_id=f"res-{rid}",
                robot_id=rid,
                resource_id="corridor-bottleneck",
                start_time=float(i * 10),
                end_time=float(i * 10 + 10),
                path_version=1,
            ))
            results.append(result)
        # All should succeed (non-overlapping: touching boundaries)
        assert all(r.success for r in results)

    def test_expired_reservations_cleaned_safely(self):
        """46. Expire + re-reserve scenario."""
        mgr = ReservationManager()
        # Fill corridor with 3 sequential reservations
        for i in range(3):
            mgr.request_reservation(_req(
                reservation_id=f"res-{i}",
                robot_id=f"amr-{i+1:02d}",
                resource_id="corridor-X",
                start_time=float(i * 10),
                end_time=float(i * 10 + 10),
                path_version=1,
            ))
        # Expire at t=25 — res-0 and res-1 should expire
        expired = mgr.expire(current_time=25.0)
        assert expired == 2
        # New reservation on the expired time range
        result = mgr.request_reservation(_req(
            reservation_id="res-new",
            robot_id="amr-04",
            resource_id="corridor-X",
            start_time=0.0, end_time=10.0,
            path_version=1,
        ))
        assert result.success is True


# =========================================================================
# 11. OWNER SAFETY
# =========================================================================


class TestOwnerSafety:
    """Owner-scoped API enforcement."""

    def test_cannot_release_another_robots_reservation(self):
        """Release with wrong robot_id fails."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
        ))
        assert mgr.release_reservation("res-1", "amr-02") is False
        assert mgr.get_reservation("res-1").status == ReservationStatus.CONFIRMED

    def test_cannot_renew_another_robots_reservation(self):
        """Renewal with wrong robot_id fails."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", robot_id="amr-01",
            start_time=10.0, end_time=20.0,
        ))
        result = mgr.renew("res-1", "amr-02", new_end_time=30.0, current_time=15.0)
        assert result.success is False


# =========================================================================
# 12. QUERY API
# =========================================================================


class TestQueryAPI:
    """Query API coverage."""

    def test_is_available(self):
        """is_available returns correct availability."""
        mgr = ReservationManager()
        assert mgr.is_available("corridor-A1", 10.0, 20.0) is True
        mgr.request_reservation(_req(start_time=10.0, end_time=20.0))
        assert mgr.is_available("corridor-A1", 10.0, 20.0) is False
        assert mgr.is_available("corridor-A1", 20.0, 30.0) is True

    def test_find_conflicts_returns_copies(self):
        """find_conflicts returns reservation copies."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(start_time=10.0, end_time=20.0))
        conflicts = mgr.find_conflicts("corridor-A1", 15.0, 25.0)
        assert len(conflicts) == 1
        assert conflicts[0].reservation_id == "res-1"

    def test_get_robot_reservations(self):
        """get_robot_reservations returns all for a robot."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", resource_id="corridor-B1",
        ))
        rlist = mgr.get_robot_reservations("amr-01")
        assert len(rlist) == 2

    def test_get_active_reservations(self):
        """get_active_reservations filters by current_time."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", start_time=10.0, end_time=20.0,
            resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", start_time=25.0, end_time=35.0,
            resource_id="corridor-B1",
        ))
        active_at_15 = mgr.get_active_reservations(15.0)
        assert len(active_at_15) == 1
        assert active_at_15[0].reservation_id == "res-1"

    def test_get_resource_reservations(self):
        """get_resource_reservations filters by resource + time."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-1", resource_id="corridor-A1",
            start_time=10.0, end_time=20.0,
        ))
        mgr.request_reservation(_req(
            reservation_id="res-2", resource_id="corridor-B1",
            start_time=10.0, end_time=20.0,
        ))
        res = mgr.get_resource_reservations("corridor-A1", 15.0)
        assert len(res) == 1
        assert res[0].resource_id == "corridor-A1"

    def test_get_reservations_for_path(self):
        """get_reservations_for_path returns path-version-specific list."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(
            reservation_id="res-v1", path_version=1,
            resource_id="corridor-A1",
        ))
        mgr.request_reservation(_req(
            reservation_id="res-v2", path_version=2,
            resource_id="corridor-B1",
        ))
        v1_list = mgr.get_reservations_for_path("amr-01", 1)
        assert len(v1_list) == 1
        assert v1_list[0].path_version == 1


# =========================================================================
# 13. DETERMINISM
# =========================================================================


class TestDeterminism:
    """Verify deterministic behaviour for identical inputs."""

    def test_same_input_same_result(self):
        """Same initial state + same requests → identical outcomes."""
        for _ in range(3):
            mgr = ReservationManager()
            r1 = mgr.request_reservation(_req(
                reservation_id="res-1", robot_id="amr-01",
                resource_id="corridor-A1",
                start_time=10.0, end_time=20.0,
            ))
            r2 = mgr.request_reservation(_req(
                reservation_id="res-2", robot_id="amr-02",
                resource_id="corridor-A1",
                start_time=15.0, end_time=25.0,
            ))
            assert r1.success is True
            assert r2.success is False
            assert r2.conflicts[0].conflicting_reservation_id == "res-1"

    def test_query_ordering_deterministic(self):
        """Query results are sorted deterministically."""
        mgr = ReservationManager()
        for i in range(5):
            mgr.request_reservation(_req(
                reservation_id=f"res-{i}",
                resource_id=f"corridor-{i}",
                start_time=float(i),
                end_time=float(i + 5),
            ))
        rlist = mgr.get_robot_reservations("amr-01")
        for i in range(len(rlist) - 1):
            assert rlist[i].start_time <= rlist[i + 1].start_time


# =========================================================================
# 14. CLEAR
# =========================================================================


class TestClear:
    """Manager clear operation."""

    def test_clear_removes_everything(self):
        """clear() empties all internal state."""
        mgr = ReservationManager()
        mgr.request_reservation(_req(reservation_id="res-1"))
        mgr.request_reservation(_req(
            reservation_id="res-2", resource_id="corridor-B1",
        ))
        mgr.clear()
        assert mgr.get_reservation("res-1") is None
        assert mgr.get_reservation("res-2") is None
        assert mgr.get_robot_reservations("amr-01") == []
        # Can re-reserve after clear
        result = mgr.request_reservation(_req(reservation_id="res-3"))
        assert result.success is True


# =========================================================================
# 15. SERIALIZATION
# =========================================================================


class TestSerialization:
    """Reservation model serialization round-trips."""

    def test_reservation_json_roundtrip(self):
        """Reservation serializes and deserializes correctly."""
        r = Reservation(
            reservation_id="res-1",
            robot_id="amr-01",
            resource_id="corridor-A1",
            start_time=10.0,
            end_time=20.0,
            path_version=3,
            status=ReservationStatus.CONFIRMED,
            created_at=5.0,
            source_conflict_id="conflict-x",
        )
        json_str = r.model_dump_json()
        reconstructed = Reservation.model_validate_json(json_str)
        assert reconstructed.reservation_id == "res-1"
        assert reconstructed.status == ReservationStatus.CONFIRMED
        assert reconstructed.path_version == 3
        assert reconstructed.source_conflict_id == "conflict-x"

    def test_reservation_result_json_roundtrip(self):
        """ReservationResult serializes and deserializes correctly."""
        mgr = ReservationManager()
        result = mgr.request_reservation(_req(
            source_conflict_id="conflict-z",
        ))
        json_str = result.model_dump_json()
        reconstructed = ReservationResult.model_validate_json(json_str)
        assert reconstructed.success is True
        assert len(reconstructed.reservations) == 1


# =========================================================================
# 16. STRESS TEST
# =========================================================================


class TestStress:
    """Performance / scale verification."""

    def test_fifty_robots_sequential_corridor(self):
        """50 robots with non-overlapping time slots on one corridor."""
        mgr = ReservationManager()
        for i in range(50):
            result = mgr.request_reservation(_req(
                reservation_id=f"res-{i:03d}",
                robot_id=f"amr-{i:03d}",
                resource_id="corridor-main",
                start_time=float(i * 10),
                end_time=float(i * 10 + 10),
                path_version=1,
            ))
            assert result.success is True
        # All 50 confirmed
        assert len(mgr.get_robot_reservations(f"amr-{0:03d}")) == 1

    def test_hundred_robots_different_resources(self):
        """100 robots on different resources — no conflicts."""
        mgr = ReservationManager()
        for i in range(100):
            result = mgr.request_reservation(_req(
                reservation_id=f"res-{i:03d}",
                robot_id=f"amr-{i:03d}",
                resource_id=f"corridor-{i:03d}",
                start_time=0.0, end_time=10.0,
                path_version=1,
            ))
            assert result.success is True
