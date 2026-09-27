"""
SWARMOS Coordination — Spatio-Temporal Corridor Reservation Engine

Provides deterministic, local-first spatio-temporal resource locking for
warehouse coordination.  Each reservation locks a named resource (corridor
segment, intersection, aisle region, etc.) for a specific robot during a
bounded time interval.

Architecture position
---------------------
::

    AMRState
       ↓
    MovementIntent
       ↓
    ConflictDetector
       ↓
    ReservationManager        ← this module
       ↓
    spatio-temporal resource lock
       ↓
    future auction / negotiation layer  (Step 4)

Resource identity
-----------------
A ``resource_id`` is an opaque string — e.g. ``"corridor-A3"``,
``"intersection-5-10"``, ``"aisle-north-2"``.  The manager does not
interpret it; equality is string equality.  The upstream caller (future
warehouse-graph or path-to-resource mapper) derives resource IDs from
the warehouse topology.

Overlap semantics (half-open intervals)
---------------------------------------
Reservations use half-open intervals ``[start_time, end_time)``.

The core overlap rule::

    candidate.start_time < existing.end_time
    AND
    existing.start_time < candidate.end_time

Therefore:

- ``[10, 13)`` and ``[13, 16)`` do **NOT** overlap  (touching boundary)
- ``[10, 13)`` and ``[12, 16)`` **DO** overlap

State machine
-------------
::

    REQUESTED → CONFIRMED
    REQUESTED → REJECTED
    CONFIRMED → RELEASED
    CONFIRMED → EXPIRED
    CONFIRMED → INVALIDATED

No reverse transitions.  A ``REJECTED`` request never blocks a resource.

Concurrency model
-----------------
``ReservationManager`` is **synchronous** and **not thread-safe**.  All
operations are atomic with respect to the manager's own in-memory state.
The future decentralized negotiation layer will invoke this manager
locally on each AMR / edge coordinator.

Expiration model
----------------
Expiration is driven by an explicit caller-supplied ``current_time``.
There are no hidden ``time.time()`` calls or background threads.
A confirmed reservation whose ``end_time <= current_time`` is eligible
for transition to ``EXPIRED``.

Future auction boundary
-----------------------
This module does **not** calculate winner, loser, utility, priority,
urgency, battery preference, or deadline priority.  Those decisions
belong to Step 4 (decentralized negotiation).
"""

from __future__ import annotations

import enum
import math
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.coordination.models import _require_finite, _require_non_whitespace


# ---------------------------------------------------------------------------
# Reservation status enum & state machine
# ---------------------------------------------------------------------------

class ReservationStatus(str, enum.Enum):
    """Controlled reservation lifecycle states."""

    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    REJECTED = "REJECTED"


# Legal state transitions.  Key = current status, value = set of valid
# target statuses.
_VALID_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.REQUESTED: frozenset({
        ReservationStatus.CONFIRMED,
        ReservationStatus.REJECTED,
    }),
    ReservationStatus.CONFIRMED: frozenset({
        ReservationStatus.RELEASED,
        ReservationStatus.EXPIRED,
        ReservationStatus.INVALIDATED,
    }),
    # Terminal states — no outbound transitions.
    ReservationStatus.RELEASED: frozenset(),
    ReservationStatus.EXPIRED: frozenset(),
    ReservationStatus.INVALIDATED: frozenset(),
    ReservationStatus.REJECTED: frozenset(),
}


def is_valid_transition(
    current: ReservationStatus,
    target: ReservationStatus,
) -> bool:
    """Return whether *current* → *target* is a legal state transition."""
    return target in _VALID_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Reservation model
# ---------------------------------------------------------------------------

class Reservation(BaseModel):
    """
    Canonical spatio-temporal resource reservation.

    This is a **coordination resource lock**, not a path model.
    It records that a specific robot has exclusive use of a named
    warehouse resource during ``[start_time, end_time)``.
    """

    reservation_id: str = Field(..., min_length=1)
    robot_id: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    start_time: float
    end_time: float
    path_version: int = Field(..., ge=1)
    status: ReservationStatus = ReservationStatus.REQUESTED
    created_at: float = Field(
        ...,
        description=(
            "Caller-supplied creation timestamp (seconds).  "
            "No hidden wall-clock dependency."
        ),
    )
    source_conflict_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional traceability back to the ConflictResult or "
            "upstream event that motivated this reservation."
        ),
    )

    # -- validators ---------------------------------------------------------

    @field_validator("reservation_id")
    @classmethod
    def _reservation_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "reservation_id")

    @field_validator("robot_id")
    @classmethod
    def _robot_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "robot_id")

    @field_validator("resource_id")
    @classmethod
    def _resource_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "resource_id")

    @field_validator("start_time")
    @classmethod
    def _start_time_finite(cls, v: float) -> float:
        _require_finite(v, "start_time")
        if v < 0:
            raise ValueError("start_time must be non-negative")
        return v

    @field_validator("end_time")
    @classmethod
    def _end_time_finite(cls, v: float) -> float:
        _require_finite(v, "end_time")
        if v < 0:
            raise ValueError("end_time must be non-negative")
        return v

    @field_validator("created_at")
    @classmethod
    def _created_at_finite(cls, v: float) -> float:
        return _require_finite(v, "created_at")

    @field_validator("source_conflict_id")
    @classmethod
    def _source_conflict_id_not_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            _require_non_whitespace(v, "source_conflict_id")
        return v

    from pydantic import model_validator

    @model_validator(mode="after")
    def _start_before_end(self) -> "Reservation":
        if self.start_time >= self.end_time:
            raise ValueError(
                f"start_time ({self.start_time}) must be strictly less than "
                f"end_time ({self.end_time})"
            )
        return self


# ---------------------------------------------------------------------------
# Reservation request (input to the manager)
# ---------------------------------------------------------------------------

class ReservationRequest(BaseModel):
    """
    Validated input for requesting a reservation.

    Separate from ``Reservation`` to enforce that callers cannot
    directly set ``status`` — the manager controls lifecycle.
    """

    reservation_id: str = Field(..., min_length=1)
    robot_id: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    start_time: float
    end_time: float
    path_version: int = Field(..., ge=1)
    created_at: float
    source_conflict_id: Optional[str] = None

    @field_validator("reservation_id")
    @classmethod
    def _reservation_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "reservation_id")

    @field_validator("robot_id")
    @classmethod
    def _robot_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "robot_id")

    @field_validator("resource_id")
    @classmethod
    def _resource_id_not_whitespace(cls, v: str) -> str:
        return _require_non_whitespace(v, "resource_id")

    @field_validator("start_time")
    @classmethod
    def _start_time_finite(cls, v: float) -> float:
        _require_finite(v, "start_time")
        if v < 0:
            raise ValueError("start_time must be non-negative")
        return v

    @field_validator("end_time")
    @classmethod
    def _end_time_finite(cls, v: float) -> float:
        _require_finite(v, "end_time")
        if v < 0:
            raise ValueError("end_time must be non-negative")
        return v

    @field_validator("created_at")
    @classmethod
    def _created_at_finite(cls, v: float) -> float:
        return _require_finite(v, "created_at")

    @field_validator("source_conflict_id")
    @classmethod
    def _source_conflict_id_not_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            _require_non_whitespace(v, "source_conflict_id")
        return v

    from pydantic import model_validator

    @model_validator(mode="after")
    def _start_before_end(self) -> "ReservationRequest":
        if self.start_time >= self.end_time:
            raise ValueError(
                f"start_time ({self.start_time}) must be strictly less than "
                f"end_time ({self.end_time})"
            )
        return self


# ---------------------------------------------------------------------------
# Conflict information (returned on rejection)
# ---------------------------------------------------------------------------

class ReservationConflictInfo(BaseModel):
    """
    Structured detail about why a reservation was rejected.

    Identifies the conflicting reservation(s), resource, overlap
    interval, and owner robot(s).
    """

    conflicting_reservation_id: str
    conflicting_robot_id: str
    resource_id: str
    overlap_start: float
    overlap_end: float
    conflicting_path_version: int


# ---------------------------------------------------------------------------
# Reservation result (output of the manager)
# ---------------------------------------------------------------------------

class ReservationResult(BaseModel):
    """
    Outcome of a reservation request (single or multi-resource).

    ``success`` is ``True`` iff all requested reservations were confirmed.
    ``reservations`` contains the confirmed ``Reservation`` objects on
    success, or the failed request(s) as ``REJECTED`` reservations on
    failure.  ``conflicts`` lists the blocking reservations when
    ``success`` is ``False``.
    """

    success: bool
    reservations: list[Reservation] = Field(default_factory=list)
    conflicts: list[ReservationConflictInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reservation Manager
# ---------------------------------------------------------------------------

def _intervals_overlap(
    start_a: float, end_a: float,
    start_b: float, end_b: float,
) -> bool:
    """
    Half-open interval overlap check.

    ``[start_a, end_a)`` overlaps ``[start_b, end_b)`` iff::

        start_a < end_b AND start_b < end_a

    Therefore:

    - [10, 13) and [13, 16) → False  (touching boundary)
    - [10, 13) and [12, 16) → True
    """
    return start_a < end_b and start_b < end_a


class ReservationManager:
    """
    Deterministic, local-first spatio-temporal reservation engine.

    Maintains an in-memory collection of reservations indexed by
    reservation ID and resource ID for efficient conflict checking.

    **Synchronous** — all public methods execute atomically with
    respect to the manager's own state.  No background threads,
    no networking, no database.

    Not thread-safe.  The future decentralized auction layer will
    invoke this manager on the local process.
    """

    def __init__(self) -> None:
        # Primary store: reservation_id → Reservation
        self._by_id: dict[str, Reservation] = {}
        # Resource index: resource_id → set of reservation_ids
        self._by_resource: dict[str, set[str]] = {}

    # -- internal helpers ---------------------------------------------------

    def _index_reservation(self, r: Reservation) -> None:
        """Add a reservation to both indexes."""
        self._by_id[r.reservation_id] = r
        self._by_resource.setdefault(r.resource_id, set()).add(
            r.reservation_id,
        )

    def _remove_from_resource_index(self, r: Reservation) -> None:
        """Remove a reservation from the resource index (not from _by_id)."""
        rset = self._by_resource.get(r.resource_id)
        if rset is not None:
            rset.discard(r.reservation_id)
            if not rset:
                del self._by_resource[r.resource_id]

    def _active_reservations_for_resource(
        self, resource_id: str,
    ) -> list[Reservation]:
        """
        Return CONFIRMED reservations for *resource_id*.

        Only CONFIRMED reservations block new requests.
        """
        rid_set = self._by_resource.get(resource_id, set())
        result: list[Reservation] = []
        for rid in rid_set:
            r = self._by_id.get(rid)
            if r is not None and r.status == ReservationStatus.CONFIRMED:
                result.append(r)
        return result

    def _find_conflicts_for_request(
        self,
        resource_id: str,
        start_time: float,
        end_time: float,
        exclude_robot_id: str | None = None,
    ) -> list[ReservationConflictInfo]:
        """
        Find CONFIRMED reservations on *resource_id* that overlap
        ``[start_time, end_time)``.

        Optionally exclude a robot (used for renewal self-exclusion).
        """
        active = self._active_reservations_for_resource(resource_id)
        conflicts: list[ReservationConflictInfo] = []
        for existing in active:
            if exclude_robot_id and existing.robot_id == exclude_robot_id:
                continue
            if _intervals_overlap(
                start_time, end_time,
                existing.start_time, existing.end_time,
            ):
                overlap_start = max(start_time, existing.start_time)
                overlap_end = min(end_time, existing.end_time)
                conflicts.append(ReservationConflictInfo(
                    conflicting_reservation_id=existing.reservation_id,
                    conflicting_robot_id=existing.robot_id,
                    resource_id=resource_id,
                    overlap_start=overlap_start,
                    overlap_end=overlap_end,
                    conflicting_path_version=existing.path_version,
                ))
        # Deterministic ordering
        conflicts.sort(key=lambda c: (
            c.overlap_start,
            c.conflicting_reservation_id,
        ))
        return conflicts

    def _transition(
        self,
        reservation_id: str,
        target_status: ReservationStatus,
    ) -> Reservation:
        """
        Transition an existing reservation to *target_status*.

        Returns a new ``Reservation`` instance with the updated status
        (Pydantic models are immutable-by-default).

        Raises ``ValueError`` if the transition is illegal.
        """
        existing = self._by_id.get(reservation_id)
        if existing is None:
            raise ValueError(
                f"Reservation '{reservation_id}' not found"
            )
        if not is_valid_transition(existing.status, target_status):
            raise ValueError(
                f"Invalid transition: {existing.status.value} → "
                f"{target_status.value} for reservation '{reservation_id}'"
            )
        updated = existing.model_copy(update={"status": target_status})
        self._by_id[reservation_id] = updated
        return updated

    # -- core: atomic check-and-confirm -------------------------------------

    def request_reservation(
        self, req: ReservationRequest,
    ) -> ReservationResult:
        """
        Atomic check-and-confirm for a single resource reservation.

        1. Validate the request.
        2. Check idempotency (duplicate reservation_id).
        3. Find conflicting CONFIRMED reservations.
        4. If no conflicts → CONFIRMED.
        5. If conflicts → REJECTED (never blocks the resource).

        Returns a ``ReservationResult`` with the outcome.
        """
        # --- Idempotency check ---
        existing = self._by_id.get(req.reservation_id)
        if existing is not None:
            # Same ID, same content → return existing result
            if (
                existing.robot_id == req.robot_id
                and existing.resource_id == req.resource_id
                and existing.start_time == req.start_time
                and existing.end_time == req.end_time
                and existing.path_version == req.path_version
            ):
                return ReservationResult(
                    success=existing.status == ReservationStatus.CONFIRMED,
                    reservations=[existing],
                )
            # Same ID, different content → reject
            return ReservationResult(
                success=False,
                reservations=[],
                conflicts=[],
            )

        # --- Conflict check ---
        conflicts = self._find_conflicts_for_request(
            req.resource_id, req.start_time, req.end_time,
        )

        if conflicts:
            # Create REJECTED reservation (does NOT block the resource)
            rejected = Reservation(
                reservation_id=req.reservation_id,
                robot_id=req.robot_id,
                resource_id=req.resource_id,
                start_time=req.start_time,
                end_time=req.end_time,
                path_version=req.path_version,
                status=ReservationStatus.REJECTED,
                created_at=req.created_at,
                source_conflict_id=req.source_conflict_id,
            )
            self._index_reservation(rejected)
            return ReservationResult(
                success=False,
                reservations=[rejected],
                conflicts=conflicts,
            )

        # --- Confirm ---
        confirmed = Reservation(
            reservation_id=req.reservation_id,
            robot_id=req.robot_id,
            resource_id=req.resource_id,
            start_time=req.start_time,
            end_time=req.end_time,
            path_version=req.path_version,
            status=ReservationStatus.CONFIRMED,
            created_at=req.created_at,
            source_conflict_id=req.source_conflict_id,
        )
        self._index_reservation(confirmed)
        return ReservationResult(
            success=True,
            reservations=[confirmed],
        )

    # -- core: atomic multi-resource commit ---------------------------------

    def request_multiple(
        self, requests: list[ReservationRequest],
    ) -> ReservationResult:
        """
        Atomic multi-resource reservation: all-or-nothing.

        If ANY request conflicts, NONE are confirmed.

        Idempotency: if all requests match existing confirmed
        reservations, returns success with the existing reservations.
        """
        if not requests:
            return ReservationResult(success=True)

        # Phase 1: validate all requests, collect conflicts
        all_conflicts: list[ReservationConflictInfo] = []
        idempotent_matches: list[Reservation] = []
        new_requests: list[ReservationRequest] = []

        for req in requests:
            # Idempotency check
            existing = self._by_id.get(req.reservation_id)
            if existing is not None:
                if (
                    existing.robot_id == req.robot_id
                    and existing.resource_id == req.resource_id
                    and existing.start_time == req.start_time
                    and existing.end_time == req.end_time
                    and existing.path_version == req.path_version
                    and existing.status == ReservationStatus.CONFIRMED
                ):
                    idempotent_matches.append(existing)
                    continue
                elif (
                    existing.robot_id == req.robot_id
                    and existing.resource_id == req.resource_id
                    and existing.start_time == req.start_time
                    and existing.end_time == req.end_time
                    and existing.path_version == req.path_version
                ):
                    # Already exists but not CONFIRMED (e.g. REJECTED)
                    # Treat as idempotent non-success
                    return ReservationResult(
                        success=False,
                        reservations=[existing],
                    )
                else:
                    # Same ID, different content → reject entire batch
                    return ReservationResult(success=False)

            # Conflict check against existing reservations
            conflicts = self._find_conflicts_for_request(
                req.resource_id, req.start_time, req.end_time,
            )
            all_conflicts.extend(conflicts)
            new_requests.append(req)

        # Also check new requests against each other for intra-batch conflicts
        for i in range(len(new_requests)):
            for j in range(i + 1, len(new_requests)):
                ri, rj = new_requests[i], new_requests[j]
                if ri.resource_id == rj.resource_id:
                    if _intervals_overlap(
                        ri.start_time, ri.end_time,
                        rj.start_time, rj.end_time,
                    ):
                        all_conflicts.append(ReservationConflictInfo(
                            conflicting_reservation_id=rj.reservation_id,
                            conflicting_robot_id=rj.robot_id,
                            resource_id=rj.resource_id,
                            overlap_start=max(ri.start_time, rj.start_time),
                            overlap_end=min(ri.end_time, rj.end_time),
                            conflicting_path_version=rj.path_version,
                        ))

        # Phase 2: if any conflicts, reject ALL new requests
        if all_conflicts:
            rejected_reservations: list[Reservation] = []
            for req in new_requests:
                rejected = Reservation(
                    reservation_id=req.reservation_id,
                    robot_id=req.robot_id,
                    resource_id=req.resource_id,
                    start_time=req.start_time,
                    end_time=req.end_time,
                    path_version=req.path_version,
                    status=ReservationStatus.REJECTED,
                    created_at=req.created_at,
                    source_conflict_id=req.source_conflict_id,
                )
                self._index_reservation(rejected)
                rejected_reservations.append(rejected)
            all_conflicts.sort(key=lambda c: (
                c.overlap_start, c.conflicting_reservation_id,
            ))
            return ReservationResult(
                success=False,
                reservations=rejected_reservations,
                conflicts=all_conflicts,
            )

        # Phase 3: all clear — confirm all new requests
        confirmed_reservations: list[Reservation] = list(idempotent_matches)
        for req in new_requests:
            confirmed = Reservation(
                reservation_id=req.reservation_id,
                robot_id=req.robot_id,
                resource_id=req.resource_id,
                start_time=req.start_time,
                end_time=req.end_time,
                path_version=req.path_version,
                status=ReservationStatus.CONFIRMED,
                created_at=req.created_at,
                source_conflict_id=req.source_conflict_id,
            )
            self._index_reservation(confirmed)
            confirmed_reservations.append(confirmed)

        return ReservationResult(
            success=True,
            reservations=confirmed_reservations,
        )

    # -- release / invalidation ---------------------------------------------

    def release_reservation(
        self, reservation_id: str, robot_id: str,
    ) -> bool:
        """
        Release a single reservation.

        Owner safety: only the owning *robot_id* can release.
        Returns ``True`` if successfully released.
        """
        existing = self._by_id.get(reservation_id)
        if existing is None:
            return False
        if existing.robot_id != robot_id:
            return False
        if not is_valid_transition(existing.status, ReservationStatus.RELEASED):
            return False
        self._transition(reservation_id, ReservationStatus.RELEASED)
        return True

    def release_robot_reservations(self, robot_id: str) -> int:
        """
        Release all CONFIRMED reservations for *robot_id*.

        Returns the count of reservations released.
        """
        count = 0
        for rid, r in list(self._by_id.items()):
            if r.robot_id == robot_id and r.status == ReservationStatus.CONFIRMED:
                self._transition(rid, ReservationStatus.RELEASED)
                count += 1
        return count

    def invalidate_robot_path(
        self, robot_id: str, path_version: int,
    ) -> int:
        """
        Invalidate all CONFIRMED reservations for *robot_id* at
        *path_version*.

        Used when a robot replans (moves to a new path version).
        Returns the count of reservations invalidated.
        """
        count = 0
        for rid, r in list(self._by_id.items()):
            if (
                r.robot_id == robot_id
                and r.path_version == path_version
                and r.status == ReservationStatus.CONFIRMED
            ):
                self._transition(rid, ReservationStatus.INVALIDATED)
                count += 1
        return count

    def invalidate_all_robot_reservations(self, robot_id: str) -> int:
        """
        Invalidate all CONFIRMED reservations for *robot_id*
        (all path versions).

        Used on robot failure / heartbeat timeout.
        Returns the count of reservations invalidated.
        """
        count = 0
        for rid, r in list(self._by_id.items()):
            if r.robot_id == robot_id and r.status == ReservationStatus.CONFIRMED:
                self._transition(rid, ReservationStatus.INVALIDATED)
                count += 1
        return count

    # -- expiration ---------------------------------------------------------

    def expire(self, current_time: float) -> int:
        """
        Expire all CONFIRMED reservations whose ``end_time <= current_time``.

        Uses the explicit *current_time* — no hidden ``time.time()`` call.
        Returns the count of reservations expired.
        """
        count = 0
        for rid, r in list(self._by_id.items()):
            if (
                r.status == ReservationStatus.CONFIRMED
                and r.end_time <= current_time
            ):
                self._transition(rid, ReservationStatus.EXPIRED)
                count += 1
        return count

    # -- renewal / extension ------------------------------------------------

    def renew(
        self,
        reservation_id: str,
        robot_id: str,
        new_end_time: float,
        current_time: float,
    ) -> ReservationResult:
        """
        Extend a CONFIRMED reservation's end time.

        Requirements:
        - Reservation must exist and be CONFIRMED.
        - *robot_id* must match the reservation owner.
        - *new_end_time* must be greater than the current end_time.
        - *new_end_time* must be finite.
        - The extended interval must not conflict with other robots'
          CONFIRMED reservations.
        - The reservation's path_version is preserved.

        On success, the reservation is updated in-place (same
        reservation_id).  On failure, returns conflicts.
        """
        if not math.isfinite(new_end_time) or new_end_time < 0:
            return ReservationResult(success=False)

        existing = self._by_id.get(reservation_id)
        if existing is None:
            return ReservationResult(success=False)
        if existing.robot_id != robot_id:
            return ReservationResult(success=False)
        if existing.status != ReservationStatus.CONFIRMED:
            return ReservationResult(success=False)
        if new_end_time <= existing.end_time:
            return ReservationResult(success=False)

        # Check for conflicts in the extension interval only against
        # OTHER robots' reservations.
        conflicts = self._find_conflicts_for_request(
            existing.resource_id,
            existing.end_time,  # only check the extended portion
            new_end_time,
            exclude_robot_id=robot_id,
        )

        if conflicts:
            return ReservationResult(
                success=False,
                reservations=[existing],
                conflicts=conflicts,
            )

        # Apply renewal — create updated reservation
        renewed = existing.model_copy(update={"end_time": new_end_time})
        self._by_id[reservation_id] = renewed
        return ReservationResult(
            success=True,
            reservations=[renewed],
        )

    # -- query APIs ---------------------------------------------------------

    def is_available(
        self,
        resource_id: str,
        start_time: float,
        end_time: float,
    ) -> bool:
        """
        Check whether *resource_id* is free during ``[start_time, end_time)``.

        Returns ``True`` if no CONFIRMED reservation overlaps.
        """
        conflicts = self._find_conflicts_for_request(
            resource_id, start_time, end_time,
        )
        return len(conflicts) == 0

    def find_conflicts(
        self,
        resource_id: str,
        start_time: float,
        end_time: float,
    ) -> list[Reservation]:
        """
        Return CONFIRMED reservations on *resource_id* that overlap
        ``[start_time, end_time)``.

        Returns copies (via Pydantic ``model_copy``) to prevent
        external mutation.
        """
        active = self._active_reservations_for_resource(resource_id)
        result: list[Reservation] = []
        for r in active:
            if _intervals_overlap(
                start_time, end_time,
                r.start_time, r.end_time,
            ):
                result.append(r.model_copy())
        result.sort(key=lambda r: (r.start_time, r.reservation_id))
        return result

    def get_reservation(self, reservation_id: str) -> Reservation | None:
        """Return a copy of the reservation, or ``None``."""
        r = self._by_id.get(reservation_id)
        return r.model_copy() if r is not None else None

    def get_robot_reservations(self, robot_id: str) -> list[Reservation]:
        """Return copies of all reservations for *robot_id* (any status)."""
        result = [
            r.model_copy() for r in self._by_id.values()
            if r.robot_id == robot_id
        ]
        result.sort(key=lambda r: (r.start_time, r.reservation_id))
        return result

    def get_active_reservations(self, current_time: float) -> list[Reservation]:
        """
        Return copies of all CONFIRMED reservations whose interval
        contains *current_time*:  ``start_time <= current_time < end_time``.
        """
        result = [
            r.model_copy() for r in self._by_id.values()
            if (
                r.status == ReservationStatus.CONFIRMED
                and r.start_time <= current_time < r.end_time
            )
        ]
        result.sort(key=lambda r: (r.start_time, r.reservation_id))
        return result

    def get_resource_reservations(
        self,
        resource_id: str,
        current_time: float,
    ) -> list[Reservation]:
        """
        Return copies of CONFIRMED reservations on *resource_id*
        that are active at *current_time*.
        """
        active = self._active_reservations_for_resource(resource_id)
        result = [
            r.model_copy() for r in active
            if r.start_time <= current_time < r.end_time
        ]
        result.sort(key=lambda r: (r.start_time, r.reservation_id))
        return result

    def get_reservations_for_path(
        self,
        robot_id: str,
        path_version: int,
    ) -> list[Reservation]:
        """
        Return copies of all reservations for *robot_id* at
        *path_version* (any status).
        """
        result = [
            r.model_copy() for r in self._by_id.values()
            if r.robot_id == robot_id and r.path_version == path_version
        ]
        result.sort(key=lambda r: (r.start_time, r.reservation_id))
        return result

    def clear(self) -> None:
        """Remove all reservations and indexes."""
        self._by_id.clear()
        self._by_resource.clear()
