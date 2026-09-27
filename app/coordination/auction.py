"""
SWARMOS Coordination — Decentralized Auction / Negotiation Engine

Provides transport-agnostic contracts, a deterministic multi-attribute
utility function, and a decentralized negotiation engine for right-of-way
resolution among competing AMRs.

Architecture position
---------------------
::

    ConflictDetector  (Step 2)
         ↓
    ConflictResult
         ↓
    AuctionRequest
         ↓
    AuctionBid  (per participant)
         ↓
    NegotiationEngine           ← this module
         ↓
    Utility calculation
         ↓
    Deterministic winner selection
         ↓
    ReservationManager  (Step 3)
         ↓
    AuctionDecision  (PROCEED / WAIT / YIELD)

Decentralized convergence property
-----------------------------------
Given identical ``auction_id``, ``auction_version``, validated bid set,
``UtilityConfig``, and tie-break rules, **every participant** independently
computes the **same winner**, **same ranking**, and **same decision ID**
regardless of message arrival order.

The core ``compute_ranking`` function is a pure, module-level function
that any participant can invoke independently.

Utility model
-------------
Multi-attribute weighted-sum utility.  Every raw component is normalized
to ``[0, 1]`` before weighting.  Components (all "higher is better"):

- **priority** : task_priority  (caller-supplied, 0–1)
- **deadline** : deadline_urgency  (caller-supplied, 0–1)
- **battery**  : battery_urgency  (caller-supplied, 0–1)
- **aging**    : bounded exponential saturation of waiting_time
- **delay**    : inverse of estimated_arrival (closer = higher)
- **distance** : inverse of remaining_distance (shorter = higher)

Aging curve: ``1 - exp(-t * ln2 / half_life)``  — monotonic, bounded
to ``[0, 1)``, reaches 0.5 at ``t = half_life``.

Transport / networking
----------------------
This module adds **no** networking dependencies.  It operates on
locally available data.  The future coordination loop will use the
existing ``CoordinationMessage`` envelope to exchange bids/decisions
over whatever transport is configured.

Boundary
--------
This module does **not** move robots, call A*, implement deadlock
detection, or run failure recovery.  Those are separate layers.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field as dc_field
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.coordination.models import _require_finite, _require_non_whitespace
from app.coordination.conflict import ConflictResult
from app.coordination.reservation import (
    ReservationManager,
    ReservationRequest,
    ReservationResult,
)


# ===================================================================
# Enums
# ===================================================================

class ParticipantOutcome(str, enum.Enum):
    """Action recommendation for an auction participant."""

    PROCEED = "PROCEED"
    WAIT = "WAIT"
    YIELD = "YIELD"
    SLOW = "SLOW"
    REROUTE = "REROUTE"


class AuctionStatus(str, enum.Enum):
    """Auction lifecycle states."""

    COLLECTING_BIDS = "COLLECTING_BIDS"
    BIDS_CLOSED = "BIDS_CLOSED"
    WINNER_SELECTED = "WINNER_SELECTED"
    RESERVATION_COMMITTING = "RESERVATION_COMMITTING"
    COMMITTED = "COMMITTED"
    NO_VALID_BIDS = "NO_VALID_BIDS"
    EXPIRED = "EXPIRED"
    RESERVATION_COMMIT_FAILED = "RESERVATION_COMMIT_FAILED"
    ABORTED = "ABORTED"


class AuctionClosePolicy(str, enum.Enum):
    """When an auction can transition from COLLECTING_BIDS to BIDS_CLOSED."""

    ALL_BIDS_RECEIVED = "ALL_BIDS_RECEIVED"
    DEADLINE = "DEADLINE"
    ALL_OR_DEADLINE = "ALL_OR_DEADLINE"


# ===================================================================
# Auction state machine
# ===================================================================

_VALID_AUCTION_TRANSITIONS: dict[
    AuctionStatus, frozenset[AuctionStatus]
] = {
    AuctionStatus.COLLECTING_BIDS: frozenset({
        AuctionStatus.BIDS_CLOSED,
        AuctionStatus.NO_VALID_BIDS,
        AuctionStatus.EXPIRED,
        AuctionStatus.ABORTED,
    }),
    AuctionStatus.BIDS_CLOSED: frozenset({
        AuctionStatus.WINNER_SELECTED,
        AuctionStatus.NO_VALID_BIDS,
    }),
    AuctionStatus.WINNER_SELECTED: frozenset({
        AuctionStatus.RESERVATION_COMMITTING,
    }),
    AuctionStatus.RESERVATION_COMMITTING: frozenset({
        AuctionStatus.COMMITTED,
        AuctionStatus.RESERVATION_COMMIT_FAILED,
    }),
    # Terminal states — no outbound transitions
    AuctionStatus.COMMITTED: frozenset(),
    AuctionStatus.NO_VALID_BIDS: frozenset(),
    AuctionStatus.EXPIRED: frozenset(),
    AuctionStatus.RESERVATION_COMMIT_FAILED: frozenset(),
    AuctionStatus.ABORTED: frozenset(),
}


def is_valid_auction_transition(
    current: AuctionStatus, target: AuctionStatus,
) -> bool:
    """Return whether *current* → *target* is a legal auction transition."""
    return target in _VALID_AUCTION_TRANSITIONS.get(current, frozenset())


# ===================================================================
# Utility configuration
# ===================================================================

class UtilityConfig(BaseModel):
    """
    Configurable weights and parameters for the multi-attribute
    right-of-way utility function.

    All weights are non-negative.  The effective utility is a weighted
    sum of components each normalized to ``[0, 1]``.  If weights sum
    to 1.0 the effective utility is bounded to ``[0, 1]``.

    Defaults are reasonable starting points for warehouse AMR
    coordination, **not** claimed to be globally optimal.

    Weight semantics
    ----------------
    - ``priority_weight``  (0.30): task importance / urgency class
    - ``deadline_weight``  (0.25): proximity to hard delivery deadline
    - ``battery_weight``   (0.15): need for charging urgency
    - ``aging_weight``     (0.15): anti-starvation from repeated losses
    - ``delay_weight``     (0.10): closeness of arrival (ETA)
    - ``distance_weight``  (0.05): remaining path length
    """

    priority_weight: float = Field(default=0.30, ge=0.0)
    deadline_weight: float = Field(default=0.25, ge=0.0)
    battery_weight: float = Field(default=0.15, ge=0.0)
    aging_weight: float = Field(default=0.15, ge=0.0)
    delay_weight: float = Field(default=0.10, ge=0.0)
    distance_weight: float = Field(default=0.05, ge=0.0)

    aging_half_life: float = Field(
        default=60.0, gt=0.0,
        description="Seconds for aging to reach 50 % of max contribution.",
    )
    max_distance: float = Field(
        default=100.0, gt=0.0,
        description="Reference distance (m) for normalization.",
    )
    max_arrival_time: float = Field(
        default=120.0, gt=0.0,
        description="Reference arrival time (s) for normalization.",
    )


# ===================================================================
# Utility breakdown (explainability)
# ===================================================================

class UtilityBreakdown(BaseModel):
    """
    Explainable breakdown of a single bid's computed utility.

    Each component is in ``[0, weight]`` where *weight* comes from
    ``UtilityConfig``.  ``effective_utility`` is their sum.

    This structure is the answer to "why did this robot get this score?"
    — no LLM-generated prose, just the actual calculated numbers.
    """

    priority_component: float
    deadline_component: float
    battery_component: float
    aging_component: float
    delay_component: float
    distance_component: float
    effective_utility: float


# ===================================================================
# Pure utility functions
# ===================================================================

def calculate_aging(waiting_time: float, config: UtilityConfig) -> float:
    """
    Bounded, monotonically increasing aging contribution.

    Uses exponential saturation::

        aging = 1 - exp(-t × ln2 / half_life)

    Properties:

    - ``t = 0``         → 0.0
    - ``t = half_life``  → ≈ 0.5
    - ``t → ∞``         → approaches 1.0 (bounded, never exceeds)
    - Monotonically increasing for ``t ≥ 0``
    - No hidden wall-clock dependency

    Returns a value in ``[0.0, 1.0)``.
    """
    if waiting_time <= 0.0:
        return 0.0
    raw = 1.0 - math.exp(
        -waiting_time * math.log(2.0) / config.aging_half_life
    )
    return max(0.0, min(1.0, raw))


def calculate_utility(
    bid: AuctionBid, config: UtilityConfig,
) -> UtilityBreakdown:
    """
    Pure, deterministic multi-attribute utility calculation.

    Same inputs → same output on every machine, regardless of
    call order, locale, or platform.

    All raw inputs are clamped to ``[0, 1]`` before weighting:

    - **priority** = ``task_priority`` (already 0–1)
    - **deadline** = ``deadline_urgency`` (already 0–1)
    - **battery** = ``battery_urgency`` (already 0–1, higher = more urgent)
    - **aging** = bounded exponential of ``waiting_time``
    - **delay** = ``1 − min(1, arrival / max_arrival)`` (closer = higher)
    - **distance** = ``1 − min(1, distance / max_distance)`` (shorter = higher)
    """
    p_raw = max(0.0, min(1.0, bid.task_priority))
    d_raw = max(0.0, min(1.0, bid.deadline_urgency))
    b_raw = max(0.0, min(1.0, bid.battery_urgency))
    a_raw = calculate_aging(bid.waiting_time, config)
    dl_raw = 1.0 - min(
        1.0, max(0.0, bid.estimated_arrival / config.max_arrival_time),
    )
    ds_raw = 1.0 - min(
        1.0, max(0.0, bid.remaining_distance / config.max_distance),
    )

    pc = p_raw * config.priority_weight
    dc = d_raw * config.deadline_weight
    bc = b_raw * config.battery_weight
    ac = a_raw * config.aging_weight
    dlc = dl_raw * config.delay_weight
    dsc = ds_raw * config.distance_weight

    return UtilityBreakdown(
        priority_component=pc,
        deadline_component=dc,
        battery_component=bc,
        aging_component=ac,
        delay_component=dlc,
        distance_component=dsc,
        effective_utility=pc + dc + bc + ac + dlc + dsc,
    )


# ===================================================================
# Auction contracts
# ===================================================================

class AuctionRequest(BaseModel):
    """
    Request to initiate a right-of-way auction for a contested resource.

    The ``participant_ids`` set is **explicit** — only locally relevant
    competitors participate; this is not a fleet-wide broadcast.
    """

    auction_id: str = Field(..., min_length=1)
    auction_version: int = Field(..., ge=1)
    requester_id: str = Field(..., min_length=1)
    participant_ids: list[str]
    resource_id: str = Field(..., min_length=1)
    time_window_start: float
    time_window_end: float
    source_conflict_id: Optional[str] = None
    path_versions: dict[str, int] = Field(default_factory=dict)
    created_at: float
    deadline: float
    close_policy: AuctionClosePolicy = AuctionClosePolicy.ALL_OR_DEADLINE

    # -- validators --

    @field_validator("auction_id")
    @classmethod
    def _aid_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "auction_id")

    @field_validator("requester_id")
    @classmethod
    def _req_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "requester_id")

    @field_validator("resource_id")
    @classmethod
    def _res_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "resource_id")

    @field_validator("time_window_start")
    @classmethod
    def _tws_ok(cls, v: float) -> float:
        _require_finite(v, "time_window_start")
        if v < 0:
            raise ValueError("time_window_start must be non-negative")
        return v

    @field_validator("time_window_end")
    @classmethod
    def _twe_ok(cls, v: float) -> float:
        _require_finite(v, "time_window_end")
        if v < 0:
            raise ValueError("time_window_end must be non-negative")
        return v

    @field_validator("created_at")
    @classmethod
    def _ca_ok(cls, v: float) -> float:
        return _require_finite(v, "created_at")

    @field_validator("deadline")
    @classmethod
    def _dl_ok(cls, v: float) -> float:
        return _require_finite(v, "deadline")

    @field_validator("participant_ids")
    @classmethod
    def _pids_ok(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("At least 2 participants required")
        seen: set[str] = set()
        for pid in v:
            _require_non_whitespace(pid, "participant_id")
            if pid in seen:
                raise ValueError(f"Duplicate participant '{pid}'")
            seen.add(pid)
        return sorted(v)  # deterministic ordering

    @field_validator("source_conflict_id")
    @classmethod
    def _sci_ok(cls, v: str | None) -> str | None:
        if v is not None:
            _require_non_whitespace(v, "source_conflict_id")
        return v

    @model_validator(mode="after")
    def _time_window_valid(self) -> AuctionRequest:
        if self.time_window_start >= self.time_window_end:
            raise ValueError(
                "time_window_start must be strictly less than time_window_end"
            )
        return self


class AuctionBid(BaseModel):
    """
    A participant's bid in a right-of-way auction.

    Contains the raw decision inputs that the utility function consumes.
    The effective utility is **not** pre-computed here — it is calculated
    by ``calculate_utility`` using the shared ``UtilityConfig``.
    """

    auction_id: str = Field(..., min_length=1)
    auction_version: int = Field(..., ge=1)
    robot_id: str = Field(..., min_length=1)
    path_version: int = Field(..., ge=1)

    # Utility inputs — caller-supplied, all in documented ranges
    task_priority: float = Field(..., ge=0.0, le=1.0)
    deadline_urgency: float = Field(..., ge=0.0, le=1.0)
    battery_urgency: float = Field(..., ge=0.0, le=1.0)
    estimated_arrival: float = Field(..., ge=0.0)
    remaining_distance: float = Field(..., ge=0.0)
    waiting_time: float = Field(..., ge=0.0)

    bid_timestamp: float
    bid_sequence: int = Field(..., ge=0)

    # -- validators --

    @field_validator("auction_id")
    @classmethod
    def _aid_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "auction_id")

    @field_validator("robot_id")
    @classmethod
    def _rid_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "robot_id")

    @field_validator("estimated_arrival")
    @classmethod
    def _ea_fin(cls, v: float) -> float:
        return _require_finite(v, "estimated_arrival")

    @field_validator("remaining_distance")
    @classmethod
    def _rd_fin(cls, v: float) -> float:
        return _require_finite(v, "remaining_distance")

    @field_validator("waiting_time")
    @classmethod
    def _wt_fin(cls, v: float) -> float:
        return _require_finite(v, "waiting_time")

    @field_validator("bid_timestamp")
    @classmethod
    def _bt_fin(cls, v: float) -> float:
        return _require_finite(v, "bid_timestamp")


# ===================================================================
# Ranked participant (within a decision)
# ===================================================================

class RankedParticipant(BaseModel):
    """One participant's rank, utility breakdown, and outcome."""

    robot_id: str
    rank: int = Field(..., ge=1)
    utility_breakdown: UtilityBreakdown
    outcome: ParticipantOutcome


# ===================================================================
# Auction decision
# ===================================================================

class AuctionDecision(BaseModel):
    """
    Outcome of a completed auction.

    Contains the deterministic ranking, winner identity, reservation
    result, and per-participant action recommendations.

    When ``status`` is ``NO_VALID_BIDS``, ``winner_id`` is empty and
    ``ranking`` is empty.
    """

    auction_id: str = Field(..., min_length=1)
    auction_version: int = Field(..., ge=1)
    decision_id: str = Field(..., min_length=1)
    winner_id: str = Field(default="")
    participant_ids: list[str] = Field(default_factory=list)
    resource_id: str = Field(default="")
    time_window_start: float = 0.0
    time_window_end: float = 0.0
    winning_utility: float = 0.0
    status: AuctionStatus = AuctionStatus.COMMITTED
    ranking: list[RankedParticipant] = Field(default_factory=list)
    reservation_result: Optional[ReservationResult] = None

    @field_validator("auction_id")
    @classmethod
    def _aid_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "auction_id")

    @field_validator("decision_id")
    @classmethod
    def _did_nw(cls, v: str) -> str:
        return _require_non_whitespace(v, "decision_id")


# ===================================================================
# Bid result (feedback to bidder)
# ===================================================================

class BidResult(BaseModel):
    """Outcome of submitting a bid."""

    accepted: bool
    reason: str = ""


# ===================================================================
# Deterministic winner selection — PURE FUNCTION
# ===================================================================

def compute_ranking(
    bids: list[AuctionBid],
    config: UtilityConfig,
) -> list[RankedParticipant]:
    """
    Pure, deterministic ranking of bids by effective utility.

    **Tie-break hierarchy** (all deterministic):

    1. Higher ``effective_utility``
    2. Higher ``aging_component`` (longer waiting time)
    3. Higher ``deadline_component``
    4. Lower ``robot_id`` (lexicographic — stable, platform-independent)

    This function is **module-level** so that every participant can
    invoke it independently.  Given identical inputs, every participant
    derives the **same ranking** regardless of message arrival order.

    Winner (rank 1) receives ``PROCEED``.
    Rank 2 receives ``WAIT``.
    Rank 3+ receive ``YIELD``.
    """
    if not bids:
        return []

    scored: list[tuple[AuctionBid, UtilityBreakdown]] = []
    for bid in bids:
        breakdown = calculate_utility(bid, config)
        scored.append((bid, breakdown))

    # Deterministic sort: utility desc, aging desc, deadline desc, id asc
    scored.sort(key=lambda x: (
        -x[1].effective_utility,
        -x[1].aging_component,
        -x[1].deadline_component,
        x[0].robot_id,
    ))

    ranking: list[RankedParticipant] = []
    for i, (bid, breakdown) in enumerate(scored):
        if i == 0:
            outcome = ParticipantOutcome.PROCEED
        elif i == 1:
            outcome = ParticipantOutcome.WAIT
        else:
            outcome = ParticipantOutcome.YIELD
        ranking.append(RankedParticipant(
            robot_id=bid.robot_id,
            rank=i + 1,
            utility_breakdown=breakdown,
            outcome=outcome,
        ))

    return ranking


def compute_decision_id(
    auction_id: str,
    auction_version: int,
    ranked: list[RankedParticipant],
) -> str:
    """
    Deterministic decision ID derived from auction identity and ranking.

    Same inputs → same ID on every participant.
    """
    ranking_key = "|".join(
        f"{r.robot_id}:{r.rank}" for r in ranked
    )
    return f"{auction_id}_v{auction_version}_{ranking_key}"


# ===================================================================
# Integration helper
# ===================================================================

def create_auction_from_conflict(
    conflict: ConflictResult,
    *,
    auction_id: str,
    resource_id: str,
    created_at: float,
    deadline: float,
    close_policy: AuctionClosePolicy = AuctionClosePolicy.ALL_OR_DEADLINE,
) -> AuctionRequest:
    """
    Create an ``AuctionRequest`` from a ``ConflictResult``.

    The caller must supply ``resource_id`` because ``ConflictResult``
    has geometric ``location`` (Position) but not a named warehouse
    resource.  The mapping from position to resource name belongs to
    the warehouse topology layer.
    """
    return AuctionRequest(
        auction_id=auction_id,
        auction_version=1,
        requester_id=conflict.robot_a_id,
        participant_ids=[conflict.robot_a_id, conflict.robot_b_id],
        resource_id=resource_id,
        time_window_start=conflict.time_window_start,
        time_window_end=conflict.time_window_end,
        source_conflict_id=None,
        path_versions={
            conflict.robot_a_id: conflict.robot_a_path_version,
            conflict.robot_b_id: conflict.robot_b_path_version,
        },
        created_at=created_at,
        deadline=deadline,
        close_policy=close_policy,
    )


# ===================================================================
# Internal session state
# ===================================================================

@dataclass
class _AuctionSession:
    """Mutable internal state for one active auction."""

    request: AuctionRequest
    status: AuctionStatus = AuctionStatus.COLLECTING_BIDS
    bids: dict[str, AuctionBid] = dc_field(default_factory=dict)
    decision: AuctionDecision | None = None


# ===================================================================
# Negotiation engine
# ===================================================================

class NegotiationEngine:
    """
    Decentralized right-of-way negotiation engine.

    Manages local auction state, bid collection, deterministic winner
    selection, and reservation commitment via the public
    ``ReservationManager`` API.

    **Synchronous**, **not thread-safe**, **no networking**.

    Decentralized convergence: the ``compute_ranking`` pure function
    guarantees that any participant with the same closed bid set and
    ``UtilityConfig`` derives the same winner independently.
    """

    def __init__(
        self,
        reservation_manager: ReservationManager,
        config: UtilityConfig | None = None,
    ) -> None:
        self._rm = reservation_manager
        self._config = config or UtilityConfig()
        self._sessions: dict[str, _AuctionSession] = {}
        self._committed_decisions: dict[str, AuctionDecision] = {}

    @property
    def config(self) -> UtilityConfig:
        """Current utility configuration (read-only)."""
        return self._config

    # -- auction lifecycle --------------------------------------------------

    def create_auction(self, request: AuctionRequest) -> str:
        """
        Register a new auction.  Returns ``auction_id``.

        Idempotent: re-registering the same auction_id + version is safe.
        Raises ``ValueError`` for version conflicts or active duplicates.
        """
        key = request.auction_id
        existing = self._sessions.get(key)

        if existing is not None:
            if existing.request.auction_version == request.auction_version:
                return key  # idempotent
            if existing.request.auction_version > request.auction_version:
                raise ValueError(
                    f"Auction '{key}' at version "
                    f"{existing.request.auction_version} supersedes "
                    f"requested version {request.auction_version}"
                )
            # Newer version — allowed only if old session is terminal
            terminal = {
                AuctionStatus.COMMITTED,
                AuctionStatus.ABORTED,
                AuctionStatus.EXPIRED,
                AuctionStatus.NO_VALID_BIDS,
                AuctionStatus.RESERVATION_COMMIT_FAILED,
            }
            if existing.status not in terminal:
                raise ValueError(
                    f"Auction '{key}' v{existing.request.auction_version} "
                    f"still active ({existing.status.value})"
                )

        self._sessions[key] = _AuctionSession(request=request)
        return key

    def abort_auction(self, auction_id: str) -> bool:
        """Abort a COLLECTING_BIDS auction.  Returns success."""
        s = self._sessions.get(auction_id)
        if s is None or s.status != AuctionStatus.COLLECTING_BIDS:
            return False
        s.status = AuctionStatus.ABORTED
        return True

    # -- bid collection -----------------------------------------------------

    def submit_bid(self, bid: AuctionBid) -> BidResult:
        """
        Submit a bid.  Validates against auction state, version,
        participant set, path-version staleness, and deduplication.
        """
        s = self._sessions.get(bid.auction_id)
        if s is None:
            return BidResult(accepted=False, reason="Auction not found")

        if s.status != AuctionStatus.COLLECTING_BIDS:
            return BidResult(
                accepted=False,
                reason=f"Auction not accepting bids ({s.status.value})",
            )

        if bid.auction_version != s.request.auction_version:
            return BidResult(
                accepted=False, reason="Auction version mismatch",
            )

        if bid.robot_id not in s.request.participant_ids:
            return BidResult(
                accepted=False,
                reason=f"'{bid.robot_id}' not in participant set",
            )

        # Path version staleness
        expected_pv = s.request.path_versions.get(bid.robot_id)
        if expected_pv is not None and bid.path_version < expected_pv:
            return BidResult(
                accepted=False,
                reason=(
                    f"Stale path_version {bid.path_version} "
                    f"< expected {expected_pv}"
                ),
            )

        # Duplicate / supersession
        prev = s.bids.get(bid.robot_id)
        if prev is not None:
            if (
                prev.bid_sequence == bid.bid_sequence
                and prev.bid_timestamp == bid.bid_timestamp
                and prev.path_version == bid.path_version
                and prev.task_priority == bid.task_priority
                and prev.deadline_urgency == bid.deadline_urgency
                and prev.battery_urgency == bid.battery_urgency
                and prev.estimated_arrival == bid.estimated_arrival
                and prev.remaining_distance == bid.remaining_distance
                and prev.waiting_time == bid.waiting_time
            ):
                return BidResult(
                    accepted=True, reason="Duplicate bid (idempotent)",
                )
            if bid.bid_sequence <= prev.bid_sequence:
                return BidResult(
                    accepted=False,
                    reason=(
                        f"Bid sequence {bid.bid_sequence} "
                        f"<= existing {prev.bid_sequence}"
                    ),
                )

        s.bids[bid.robot_id] = bid
        return BidResult(accepted=True, reason="Bid accepted")

    # -- closing / decision -------------------------------------------------

    def is_ready_to_close(
        self, auction_id: str, current_time: float,
    ) -> bool:
        """Check whether the auction can be closed per its close policy."""
        s = self._sessions.get(auction_id)
        if s is None or s.status != AuctionStatus.COLLECTING_BIDS:
            return False
        all_in = len(s.bids) >= len(s.request.participant_ids)
        past_deadline = current_time >= s.request.deadline
        policy = s.request.close_policy
        if policy == AuctionClosePolicy.ALL_BIDS_RECEIVED:
            return all_in
        if policy == AuctionClosePolicy.DEADLINE:
            return past_deadline
        return all_in or past_deadline  # ALL_OR_DEADLINE

    def try_close_auction(
        self, auction_id: str, current_time: float,
    ) -> AuctionDecision | None:
        """Close and decide if ready; returns ``None`` if not ready."""
        if not self.is_ready_to_close(auction_id, current_time):
            return None
        return self.close_auction(auction_id, current_time)

    def close_auction(
        self, auction_id: str, current_time: float,
    ) -> AuctionDecision:
        """
        Force-close the auction and compute the winner.

        Flow: COLLECTING_BIDS → BIDS_CLOSED → WINNER_SELECTED
              → RESERVATION_COMMITTING → COMMITTED / FAILED

        Or: → NO_VALID_BIDS if no bids received.

        Idempotent: if already decided, returns the existing decision.
        """
        s = self._sessions.get(auction_id)
        if s is None:
            raise ValueError(f"Auction '{auction_id}' not found")

        # Idempotent re-close
        if s.decision is not None:
            return s.decision

        if s.status != AuctionStatus.COLLECTING_BIDS:
            raise ValueError(
                f"Cannot close auction '{auction_id}' "
                f"from status {s.status.value}"
            )

        req = s.request
        bids_list = list(s.bids.values())

        # -- no valid bids --
        if not bids_list:
            s.status = AuctionStatus.NO_VALID_BIDS
            decision = AuctionDecision(
                auction_id=req.auction_id,
                auction_version=req.auction_version,
                decision_id=f"{req.auction_id}_v{req.auction_version}_no_bids",
                winner_id="",
                participant_ids=list(req.participant_ids),
                resource_id=req.resource_id,
                time_window_start=req.time_window_start,
                time_window_end=req.time_window_end,
                winning_utility=0.0,
                status=AuctionStatus.NO_VALID_BIDS,
                ranking=[],
            )
            s.decision = decision
            return decision

        # -- close bids + rank --
        s.status = AuctionStatus.BIDS_CLOSED
        ranking = compute_ranking(bids_list, self._config)
        s.status = AuctionStatus.WINNER_SELECTED

        winner = ranking[0]
        decision_id = compute_decision_id(
            req.auction_id, req.auction_version, ranking,
        )

        # Decision idempotency
        if decision_id in self._committed_decisions:
            cached = self._committed_decisions[decision_id]
            s.decision = cached
            s.status = cached.status
            return cached

        # Find winning bid for path_version
        winner_bid = next(
            b for b in bids_list if b.robot_id == winner.robot_id
        )

        # -- reservation commit --
        s.status = AuctionStatus.RESERVATION_COMMITTING

        res_req = ReservationRequest(
            reservation_id=(
                f"auction_{req.auction_id}"
                f"_v{req.auction_version}"
                f"_{winner.robot_id}"
            ),
            robot_id=winner.robot_id,
            resource_id=req.resource_id,
            start_time=req.time_window_start,
            end_time=req.time_window_end,
            path_version=winner_bid.path_version,
            created_at=current_time,
            source_conflict_id=req.source_conflict_id,
        )
        res_result = self._rm.request_reservation(res_req)

        if res_result.success:
            final_status = AuctionStatus.COMMITTED
        else:
            final_status = AuctionStatus.RESERVATION_COMMIT_FAILED

        s.status = final_status

        decision = AuctionDecision(
            auction_id=req.auction_id,
            auction_version=req.auction_version,
            decision_id=decision_id,
            winner_id=winner.robot_id,
            participant_ids=list(req.participant_ids),
            resource_id=req.resource_id,
            time_window_start=req.time_window_start,
            time_window_end=req.time_window_end,
            winning_utility=winner.utility_breakdown.effective_utility,
            status=final_status,
            ranking=ranking,
            reservation_result=res_result,
        )

        s.decision = decision
        self._committed_decisions[decision_id] = decision
        return decision

    # -- queries ------------------------------------------------------------

    def get_auction_status(self, auction_id: str) -> AuctionStatus | None:
        """Return current status, or ``None`` if unknown."""
        s = self._sessions.get(auction_id)
        return s.status if s else None

    def get_auction_decision(
        self, auction_id: str,
    ) -> AuctionDecision | None:
        """Return the decision, or ``None``."""
        s = self._sessions.get(auction_id)
        return s.decision if s else None

    def get_collected_bids(self, auction_id: str) -> list[AuctionBid]:
        """Return bids collected so far, sorted by robot_id."""
        s = self._sessions.get(auction_id)
        if s is None:
            return []
        return sorted(s.bids.values(), key=lambda b: b.robot_id)

    def get_missing_participants(self, auction_id: str) -> list[str]:
        """Return participant IDs that have not yet bid."""
        s = self._sessions.get(auction_id)
        if s is None:
            return []
        return sorted(
            pid for pid in s.request.participant_ids
            if pid not in s.bids
        )

    def validate_external_decision(
        self, decision: AuctionDecision,
    ) -> bool:
        """
        Check whether an externally received decision is consistent
        with the local view.

        Returns ``True`` if consistent or if no local decision exists
        yet (cannot disprove).  Returns ``False`` if the local decision
        disagrees on winner or decision_id.
        """
        s = self._sessions.get(decision.auction_id)
        if s is None:
            return False
        if s.decision is None:
            return True  # no local decision to compare against
        return (
            s.decision.decision_id == decision.decision_id
            and s.decision.winner_id == decision.winner_id
        )

    def clear(self) -> None:
        """Remove all auction state."""
        self._sessions.clear()
        self._committed_decisions.clear()
