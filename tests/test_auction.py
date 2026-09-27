"""
Unit tests for the decentralized auction / negotiation engine (Step 4).

All tests use explicit timestamps and deterministic inputs — no
``time.time()``, no randomness, no networking.

Organised by the Phase 4A test plan:
- Contract validation (AuctionRequest / AuctionBid / AuctionDecision)
- Utility calculation + normalization + aging
- Deterministic behaviour
- State machine
- Bid collection
- Winner selection + convergence
- Reservation integration
- Decision idempotency
- Action recommendations
- Multi-robot scenarios
- Integration with ConflictResult / ReservationManager
- Serialization round-trips
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.coordination.auction import (
    AuctionBid,
    AuctionClosePolicy,
    AuctionDecision,
    AuctionRequest,
    AuctionStatus,
    BidResult,
    NegotiationEngine,
    ParticipantOutcome,
    RankedParticipant,
    UtilityBreakdown,
    UtilityConfig,
    calculate_aging,
    calculate_utility,
    compute_decision_id,
    compute_ranking,
    create_auction_from_conflict,
    is_valid_auction_transition,
)
from app.coordination.conflict import ConflictResult, ConflictType
from app.coordination.models import Position
from app.coordination.reservation import ReservationManager


# ── helpers ──────────────────────────────────────────────────────────────

def _auction_req(
    auction_id: str = "auc-1",
    auction_version: int = 1,
    requester_id: str = "amr-01",
    participant_ids: list[str] | None = None,
    resource_id: str = "corridor-A1",
    time_window_start: float = 10.0,
    time_window_end: float = 20.0,
    created_at: float = 0.0,
    deadline: float = 100.0,
    close_policy: AuctionClosePolicy = AuctionClosePolicy.ALL_OR_DEADLINE,
    path_versions: dict[str, int] | None = None,
    source_conflict_id: str | None = None,
) -> AuctionRequest:
    pids = participant_ids if participant_ids is not None else ["amr-01", "amr-02"]
    pvs = path_versions or {}
    return AuctionRequest(
        auction_id=auction_id,
        auction_version=auction_version,
        requester_id=requester_id,
        participant_ids=pids,
        resource_id=resource_id,
        time_window_start=time_window_start,
        time_window_end=time_window_end,
        created_at=created_at,
        deadline=deadline,
        close_policy=close_policy,
        path_versions=pvs,
        source_conflict_id=source_conflict_id,
    )


def _bid(
    auction_id: str = "auc-1",
    auction_version: int = 1,
    robot_id: str = "amr-01",
    path_version: int = 1,
    task_priority: float = 0.5,
    deadline_urgency: float = 0.5,
    battery_urgency: float = 0.3,
    estimated_arrival: float = 30.0,
    remaining_distance: float = 20.0,
    waiting_time: float = 0.0,
    bid_timestamp: float = 1.0,
    bid_sequence: int = 0,
) -> AuctionBid:
    return AuctionBid(
        auction_id=auction_id,
        auction_version=auction_version,
        robot_id=robot_id,
        path_version=path_version,
        task_priority=task_priority,
        deadline_urgency=deadline_urgency,
        battery_urgency=battery_urgency,
        estimated_arrival=estimated_arrival,
        remaining_distance=remaining_distance,
        waiting_time=waiting_time,
        bid_timestamp=bid_timestamp,
        bid_sequence=bid_sequence,
    )


def _engine() -> tuple[NegotiationEngine, ReservationManager]:
    rm = ReservationManager()
    eng = NegotiationEngine(rm)
    return eng, rm


# =========================================================================
# 1. AUCTION REQUEST CONTRACT VALIDATION
# =========================================================================


class TestAuctionRequestContract:
    """Tests 1–7: AuctionRequest model validation."""

    def test_valid_request_accepted(self):
        """1. Fully valid request is constructed."""
        r = _auction_req()
        assert r.auction_id == "auc-1"
        assert r.auction_version == 1

    def test_invalid_empty_id_rejected(self):
        """2. Empty auction_id rejected."""
        with pytest.raises(ValidationError):
            _auction_req(auction_id="")

    def test_invalid_whitespace_id_rejected(self):
        """3. Whitespace-only IDs rejected."""
        with pytest.raises(ValidationError):
            _auction_req(auction_id="   ")
        with pytest.raises(ValidationError):
            _auction_req(requester_id="\t")
        with pytest.raises(ValidationError):
            _auction_req(resource_id="  ")

    def test_invalid_version_rejected(self):
        """4. Version < 1 rejected."""
        with pytest.raises(ValidationError):
            _auction_req(auction_version=0)
        with pytest.raises(ValidationError):
            _auction_req(auction_version=-1)

    def test_invalid_time_interval_rejected(self):
        """5. start >= end rejected."""
        with pytest.raises(ValidationError):
            _auction_req(time_window_start=20.0, time_window_end=10.0)
        with pytest.raises(ValidationError):
            _auction_req(time_window_start=15.0, time_window_end=15.0)

    def test_invalid_participant_set_rejected(self):
        """6. < 2 participants, duplicates, or whitespace IDs rejected."""
        with pytest.raises(ValidationError):
            _auction_req(participant_ids=["amr-01"])
        with pytest.raises(ValidationError):
            _auction_req(participant_ids=[])
        with pytest.raises(ValidationError):
            _auction_req(participant_ids=["amr-01", "amr-01"])
        with pytest.raises(ValidationError):
            _auction_req(participant_ids=["amr-01", "  "])

    def test_serialization_round_trip(self):
        """7. AuctionRequest JSON round-trip preserves all fields."""
        r = _auction_req(source_conflict_id="cf-1")
        json_str = r.model_dump_json()
        restored = AuctionRequest.model_validate_json(json_str)
        assert restored.auction_id == r.auction_id
        assert restored.source_conflict_id == "cf-1"
        assert restored.participant_ids == r.participant_ids

    def test_participant_ids_sorted_deterministically(self):
        """Participant IDs are sorted regardless of input order."""
        r1 = _auction_req(participant_ids=["amr-02", "amr-01"])
        r2 = _auction_req(participant_ids=["amr-01", "amr-02"])
        assert r1.participant_ids == r2.participant_ids

    def test_non_finite_times_rejected(self):
        """NaN / Inf rejected for time fields."""
        with pytest.raises(ValidationError):
            _auction_req(time_window_start=float("nan"))
        with pytest.raises(ValidationError):
            _auction_req(time_window_end=float("inf"))
        with pytest.raises(ValidationError):
            _auction_req(deadline=float("-inf"))


# =========================================================================
# 2. AUCTION BID CONTRACT VALIDATION
# =========================================================================


class TestAuctionBidContract:
    """Tests 8–13: AuctionBid model validation."""

    def test_valid_bid_accepted(self):
        """8. Fully valid bid is constructed."""
        b = _bid()
        assert b.robot_id == "amr-01"

    def test_invalid_robot_id_rejected(self):
        """9. Empty / whitespace robot_id rejected."""
        with pytest.raises(ValidationError):
            _bid(robot_id="")
        with pytest.raises(ValidationError):
            _bid(robot_id="  ")

    def test_invalid_path_version_rejected(self):
        """10. path_version < 1 rejected."""
        with pytest.raises(ValidationError):
            _bid(path_version=0)

    def test_invalid_negative_quantities_rejected(self):
        """11. Negative values rejected where prohibited."""
        with pytest.raises(ValidationError):
            _bid(estimated_arrival=-1.0)
        with pytest.raises(ValidationError):
            _bid(remaining_distance=-5.0)
        with pytest.raises(ValidationError):
            _bid(waiting_time=-0.1)
        with pytest.raises(ValidationError):
            _bid(task_priority=-0.1)

    def test_non_finite_values_rejected(self):
        """12. NaN / Inf rejected for numeric fields."""
        with pytest.raises(ValidationError):
            _bid(estimated_arrival=float("nan"))
        with pytest.raises(ValidationError):
            _bid(remaining_distance=float("inf"))

    def test_bid_serialization_round_trip(self):
        """13. AuctionBid JSON round-trip."""
        b = _bid()
        restored = AuctionBid.model_validate_json(b.model_dump_json())
        assert restored.robot_id == b.robot_id
        assert restored.task_priority == b.task_priority

    def test_priority_bounds(self):
        """task_priority and urgency must be 0–1."""
        with pytest.raises(ValidationError):
            _bid(task_priority=1.1)
        with pytest.raises(ValidationError):
            _bid(deadline_urgency=-0.01)
        with pytest.raises(ValidationError):
            _bid(battery_urgency=1.5)


# =========================================================================
# 3. AUCTION DECISION CONTRACT VALIDATION
# =========================================================================


class TestAuctionDecisionContract:
    """Tests 14–18: AuctionDecision model validation."""

    def test_valid_decision_accepted(self):
        """14. Fully valid decision is constructed."""
        d = AuctionDecision(
            auction_id="auc-1",
            auction_version=1,
            decision_id="dec-1",
            winner_id="amr-01",
            participant_ids=["amr-01", "amr-02"],
            resource_id="corridor-A1",
            time_window_start=10.0,
            time_window_end=20.0,
            winning_utility=0.75,
            status=AuctionStatus.COMMITTED,
            ranking=[],
        )
        assert d.winner_id == "amr-01"

    def test_no_winner_representation(self):
        """15. Empty winner_id for NO_VALID_BIDS."""
        d = AuctionDecision(
            auction_id="auc-1",
            auction_version=1,
            decision_id="dec-1",
            winner_id="",
            status=AuctionStatus.NO_VALID_BIDS,
        )
        assert d.winner_id == ""

    def test_invalid_decision_ids_rejected(self):
        """16. Empty / whitespace IDs rejected."""
        with pytest.raises(ValidationError):
            AuctionDecision(
                auction_id="", auction_version=1, decision_id="d",
            )
        with pytest.raises(ValidationError):
            AuctionDecision(
                auction_id="a", auction_version=1, decision_id="",
            )

    def test_invalid_decision_version_rejected(self):
        """17. Version < 1 rejected."""
        with pytest.raises(ValidationError):
            AuctionDecision(
                auction_id="a", auction_version=0, decision_id="d",
            )

    def test_decision_serialization_round_trip(self):
        """18. AuctionDecision JSON round-trip."""
        d = AuctionDecision(
            auction_id="auc-1",
            auction_version=1,
            decision_id="dec-1",
            winner_id="amr-01",
            status=AuctionStatus.COMMITTED,
            ranking=[RankedParticipant(
                robot_id="amr-01", rank=1,
                utility_breakdown=UtilityBreakdown(
                    priority_component=0.15, deadline_component=0.125,
                    battery_component=0.075, aging_component=0.0,
                    delay_component=0.05, distance_component=0.025,
                    effective_utility=0.425,
                ),
                outcome=ParticipantOutcome.PROCEED,
            )],
        )
        restored = AuctionDecision.model_validate_json(d.model_dump_json())
        assert restored.ranking[0].robot_id == "amr-01"
        assert restored.ranking[0].outcome == ParticipantOutcome.PROCEED


# =========================================================================
# 4. UTILITY CALCULATION
# =========================================================================


class TestUtilityCalculation:
    """Tests 19–28: deterministic utility calculation."""

    @pytest.fixture()
    def cfg(self) -> UtilityConfig:
        return UtilityConfig()

    def test_deterministic_repeated_calculation(self, cfg):
        """19. Same bid + config → same utility every time."""
        b = _bid()
        u1 = calculate_utility(b, cfg)
        u2 = calculate_utility(b, cfg)
        assert u1.effective_utility == u2.effective_utility

    def test_priority_contribution(self, cfg):
        """20. Higher task_priority → higher priority component."""
        low = calculate_utility(_bid(task_priority=0.2), cfg)
        high = calculate_utility(_bid(task_priority=0.9), cfg)
        assert high.priority_component > low.priority_component

    def test_deadline_contribution(self, cfg):
        """21. Higher deadline_urgency → higher deadline component."""
        low = calculate_utility(_bid(deadline_urgency=0.1), cfg)
        high = calculate_utility(_bid(deadline_urgency=0.9), cfg)
        assert high.deadline_component > low.deadline_component

    def test_battery_contribution(self, cfg):
        """22. Higher battery_urgency → higher battery component."""
        low = calculate_utility(_bid(battery_urgency=0.1), cfg)
        high = calculate_utility(_bid(battery_urgency=0.9), cfg)
        assert high.battery_component > low.battery_component

    def test_distance_contribution(self, cfg):
        """23. Shorter remaining_distance → higher distance component."""
        far = calculate_utility(_bid(remaining_distance=80.0), cfg)
        near = calculate_utility(_bid(remaining_distance=10.0), cfg)
        assert near.distance_component > far.distance_component

    def test_waiting_age_contribution(self, cfg):
        """24. Longer waiting_time → higher aging component."""
        no_wait = calculate_utility(_bid(waiting_time=0.0), cfg)
        waited = calculate_utility(_bid(waiting_time=120.0), cfg)
        assert waited.aging_component > no_wait.aging_component

    def test_configurable_weights(self):
        """25. Custom weights change component magnitudes."""
        heavy_prio = UtilityConfig(priority_weight=0.9, deadline_weight=0.0,
                                   battery_weight=0.0, aging_weight=0.0,
                                   delay_weight=0.0, distance_weight=0.0)
        b = _bid(task_priority=1.0)
        u = calculate_utility(b, heavy_prio)
        assert u.priority_component == pytest.approx(0.9)
        assert u.deadline_component == 0.0

    def test_normalization(self, cfg):
        """26. Components are bounded to [0, weight]."""
        # Even with extreme inputs, components stay bounded
        extreme = _bid(
            task_priority=1.0, deadline_urgency=1.0,
            battery_urgency=1.0, estimated_arrival=0.0,
            remaining_distance=0.0, waiting_time=100000.0,
        )
        u = calculate_utility(extreme, cfg)
        assert 0.0 <= u.priority_component <= cfg.priority_weight + 1e-9
        assert 0.0 <= u.deadline_component <= cfg.deadline_weight + 1e-9
        assert 0.0 <= u.battery_component <= cfg.battery_weight + 1e-9
        assert 0.0 <= u.aging_component <= cfg.aging_weight + 1e-9
        assert 0.0 <= u.delay_component <= cfg.delay_weight + 1e-9
        assert 0.0 <= u.distance_component <= cfg.distance_weight + 1e-9

    def test_boundary_values(self, cfg):
        """27. Zero and maximum inputs produce correct boundaries."""
        zero_bid = _bid(
            task_priority=0.0, deadline_urgency=0.0,
            battery_urgency=0.0, estimated_arrival=999.0,
            remaining_distance=999.0, waiting_time=0.0,
        )
        u_zero = calculate_utility(zero_bid, cfg)
        assert u_zero.effective_utility >= 0.0

        max_bid = _bid(
            task_priority=1.0, deadline_urgency=1.0,
            battery_urgency=1.0, estimated_arrival=0.0,
            remaining_distance=0.0, waiting_time=100000.0,
        )
        u_max = calculate_utility(max_bid, cfg)
        total_weight = (cfg.priority_weight + cfg.deadline_weight +
                        cfg.battery_weight + cfg.aging_weight +
                        cfg.delay_weight + cfg.distance_weight)
        assert u_max.effective_utility <= total_weight + 1e-9

    def test_breakdown_sums_to_effective(self, cfg):
        """28. Component sum equals effective_utility."""
        b = _bid(task_priority=0.7, deadline_urgency=0.3,
                 waiting_time=45.0)
        u = calculate_utility(b, cfg)
        component_sum = (
            u.priority_component + u.deadline_component +
            u.battery_component + u.aging_component +
            u.delay_component + u.distance_component
        )
        assert u.effective_utility == pytest.approx(component_sum)

    def test_delay_contribution(self, cfg):
        """Closer arrival → higher delay component."""
        far_arrival = calculate_utility(_bid(estimated_arrival=100.0), cfg)
        near_arrival = calculate_utility(_bid(estimated_arrival=10.0), cfg)
        assert near_arrival.delay_component > far_arrival.delay_component


# =========================================================================
# 5. AGING FUNCTION
# =========================================================================


class TestAgingFunction:
    """Anti-starvation aging component tests."""

    @pytest.fixture()
    def cfg(self) -> UtilityConfig:
        return UtilityConfig(aging_half_life=60.0)

    def test_zero_wait_zero_aging(self, cfg):
        """Waiting_time = 0 → aging = 0."""
        assert calculate_aging(0.0, cfg) == 0.0

    def test_negative_wait_zero_aging(self, cfg):
        """Negative waiting_time → aging = 0."""
        assert calculate_aging(-5.0, cfg) == 0.0

    def test_waiting_increases_aging(self, cfg):
        """19. More waiting → higher aging (monotonic)."""
        a30 = calculate_aging(30.0, cfg)
        a60 = calculate_aging(60.0, cfg)
        a120 = calculate_aging(120.0, cfg)
        assert 0.0 < a30 < a60 < a120

    def test_waiting_is_monotonic(self, cfg):
        """20. Strictly monotonic for positive waiting times."""
        prev = 0.0
        for t in [1, 5, 10, 30, 60, 120, 300, 600]:
            cur = calculate_aging(float(t), cfg)
            assert cur > prev
            prev = cur

    def test_waiting_is_bounded(self, cfg):
        """21. Aging never exceeds 1.0, even for extreme waits."""
        for t in [1e3, 1e6, 1e9]:
            assert calculate_aging(t, cfg) <= 1.0

    def test_half_life_at_configured_time(self, cfg):
        """At t = half_life, aging ≈ 0.5."""
        aging = calculate_aging(cfg.aging_half_life, cfg)
        assert aging == pytest.approx(0.5, abs=0.01)

    def test_identical_inputs_identical_aging(self, cfg):
        """23. Same input → same result (deterministic)."""
        a1 = calculate_aging(42.0, cfg)
        a2 = calculate_aging(42.0, cfg)
        assert a1 == a2


# =========================================================================
# 6. DETERMINISM
# =========================================================================


class TestDeterminism:
    """Tests 29–30: same inputs → same outputs."""

    def test_same_input_same_utility(self):
        """29. Repeated utility calculation on identical inputs."""
        cfg = UtilityConfig()
        b = _bid(task_priority=0.6, waiting_time=45.0)
        results = [calculate_utility(b, cfg) for _ in range(5)]
        assert all(
            r.effective_utility == results[0].effective_utility
            for r in results
        )

    def test_serialized_deserialized_same_result(self):
        """30. Serialize → deserialize → same utility."""
        cfg = UtilityConfig()
        b = _bid(task_priority=0.8, deadline_urgency=0.7)
        u_original = calculate_utility(b, cfg)
        b_restored = AuctionBid.model_validate_json(b.model_dump_json())
        u_restored = calculate_utility(b_restored, cfg)
        assert u_original.effective_utility == u_restored.effective_utility


# =========================================================================
# 7. AUCTION STATE MACHINE
# =========================================================================


class TestAuctionStateMachine:
    """Tests 46–52: state transition validation."""

    def test_valid_transitions(self):
        """46. All legal transitions accepted."""
        assert is_valid_auction_transition(
            AuctionStatus.COLLECTING_BIDS, AuctionStatus.BIDS_CLOSED,
        )
        assert is_valid_auction_transition(
            AuctionStatus.BIDS_CLOSED, AuctionStatus.WINNER_SELECTED,
        )
        assert is_valid_auction_transition(
            AuctionStatus.WINNER_SELECTED,
            AuctionStatus.RESERVATION_COMMITTING,
        )
        assert is_valid_auction_transition(
            AuctionStatus.RESERVATION_COMMITTING,
            AuctionStatus.COMMITTED,
        )

    def test_invalid_transitions_rejected(self):
        """47. Illegal transitions rejected."""
        assert not is_valid_auction_transition(
            AuctionStatus.COMMITTED, AuctionStatus.COLLECTING_BIDS,
        )
        assert not is_valid_auction_transition(
            AuctionStatus.ABORTED, AuctionStatus.COLLECTING_BIDS,
        )
        assert not is_valid_auction_transition(
            AuctionStatus.COLLECTING_BIDS,
            AuctionStatus.WINNER_SELECTED,
        )

    def test_auction_expiration(self):
        """48. Auction expires when closed past deadline with no bids."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(deadline=50.0))
        # No bids, close after deadline
        decision = eng.close_auction("auc-1", current_time=60.0)
        assert decision.status == AuctionStatus.NO_VALID_BIDS

    def test_no_valid_bids_state(self):
        """49. NO_VALID_BIDS when no bids at close."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        decision = eng.close_auction("auc-1", current_time=200.0)
        assert decision.status == AuctionStatus.NO_VALID_BIDS
        assert decision.winner_id == ""
        assert decision.ranking == []

    def test_winner_selected_on_valid_bids(self):
        """50. WINNER_SELECTED flows to COMMITTED on success."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.COMMITTED
        assert decision.winner_id == "amr-01"

    def test_commit_failure_state(self):
        """51. RESERVATION_COMMIT_FAILED when resource already taken."""
        eng, rm = _engine()
        # Pre-reserve the resource
        from app.coordination.reservation import ReservationRequest
        rm.request_reservation(ReservationRequest(
            reservation_id="pre-lock", robot_id="amr-99",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=0.0,
        ))
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.RESERVATION_COMMIT_FAILED

    def test_committed_is_terminal(self):
        """52. COMMITTED has no outbound transitions."""
        assert not is_valid_auction_transition(
            AuctionStatus.COMMITTED, AuctionStatus.COLLECTING_BIDS,
        )
        assert not is_valid_auction_transition(
            AuctionStatus.COMMITTED, AuctionStatus.ABORTED,
        )

    def test_abort_auction(self):
        """Abort transitions to ABORTED from COLLECTING_BIDS only."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        assert eng.abort_auction("auc-1") is True
        assert eng.get_auction_status("auc-1") == AuctionStatus.ABORTED
        # Cannot abort again
        assert eng.abort_auction("auc-1") is False


# =========================================================================
# 8. BID COLLECTION
# =========================================================================


class TestBidCollection:
    """Tests 24–34: bid submission and collection."""

    def test_one_valid_bid(self):
        """24. Single valid bid accepted."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        r = eng.submit_bid(_bid(robot_id="amr-01"))
        assert r.accepted is True

    def test_two_competitors(self):
        """25. Two valid bids from different robots."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        r1 = eng.submit_bid(_bid(robot_id="amr-01"))
        r2 = eng.submit_bid(_bid(robot_id="amr-02"))
        assert r1.accepted and r2.accepted

    def test_n_competitors(self):
        """26. N competitors all accepted."""
        pids = [f"amr-{i:02d}" for i in range(1, 6)]
        eng, _ = _engine()
        eng.create_auction(_auction_req(participant_ids=pids))
        for pid in pids:
            r = eng.submit_bid(_bid(robot_id=pid))
            assert r.accepted

    def test_duplicate_identical_bid_idempotent(self):
        """27. Same bid twice → idempotent."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        b = _bid(robot_id="amr-01")
        r1 = eng.submit_bid(b)
        r2 = eng.submit_bid(b)
        assert r1.accepted and r2.accepted
        assert "idempotent" in r2.reason.lower()

    def test_conflicting_duplicate_bid_rejected(self):
        """28. Same robot+sequence, different content → rejected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=0,
                            task_priority=0.5))
        r = eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=0,
                                task_priority=0.9))
        assert r.accepted is False

    def test_stale_bid_rejected(self):
        """29. Older bid_sequence rejected after newer one."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=5))
        r = eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=3,
                                task_priority=0.9))
        assert r.accepted is False

    def test_invalid_bid_non_participant_rejected(self):
        """30. Non-participant bid rejected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        r = eng.submit_bid(_bid(robot_id="amr-99"))
        assert r.accepted is False

    def test_all_expected_bids_received(self):
        """31. is_ready_to_close when all bids in."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            close_policy=AuctionClosePolicy.ALL_BIDS_RECEIVED,
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        assert not eng.is_ready_to_close("auc-1", 0.0)
        eng.submit_bid(_bid(robot_id="amr-02"))
        assert eng.is_ready_to_close("auc-1", 0.0)

    def test_deadline_based_close(self):
        """32. DEADLINE policy closes at deadline regardless of bids."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            deadline=50.0,
            close_policy=AuctionClosePolicy.DEADLINE,
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        assert not eng.is_ready_to_close("auc-1", 40.0)
        assert eng.is_ready_to_close("auc-1", 50.0)

    def test_missing_participant_handling(self):
        """33. get_missing_participants tracks who hasn't bid."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            participant_ids=["amr-01", "amr-02", "amr-03"],
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        missing = eng.get_missing_participants("auc-1")
        assert "amr-02" in missing
        assert "amr-03" in missing
        assert "amr-01" not in missing

    def test_arrival_order_independence(self):
        """34. Different bid arrival order → same close readiness."""
        for order in [["amr-01", "amr-02"], ["amr-02", "amr-01"]]:
            eng, _ = _engine()
            eng.create_auction(_auction_req(
                close_policy=AuctionClosePolicy.ALL_BIDS_RECEIVED,
            ))
            for rid in order:
                eng.submit_bid(_bid(robot_id=rid))
            assert eng.is_ready_to_close("auc-1", 0.0)

    def test_bid_to_nonexistent_auction_rejected(self):
        """Bid to unknown auction rejected."""
        eng, _ = _engine()
        r = eng.submit_bid(_bid(auction_id="ghost"))
        assert r.accepted is False

    def test_bid_version_mismatch_rejected(self):
        """Bid with wrong auction_version rejected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(auction_version=2))
        r = eng.submit_bid(_bid(auction_version=1))
        assert r.accepted is False

    def test_stale_path_version_rejected(self):
        """Bid with path_version < expected rejected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            path_versions={"amr-01": 3, "amr-02": 1},
        ))
        r = eng.submit_bid(_bid(robot_id="amr-01", path_version=2))
        assert r.accepted is False
        # Same or newer version accepted
        r2 = eng.submit_bid(_bid(robot_id="amr-01", path_version=3))
        assert r2.accepted is True

    def test_superseding_bid_accepted(self):
        """Newer bid_sequence supersedes older bid."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=0,
                            task_priority=0.3))
        r = eng.submit_bid(_bid(robot_id="amr-01", bid_sequence=1,
                                task_priority=0.9))
        assert r.accepted is True
        bids = eng.get_collected_bids("auc-1")
        amr01_bid = next(b for b in bids if b.robot_id == "amr-01")
        assert amr01_bid.task_priority == pytest.approx(0.9)


# =========================================================================
# 9. WINNER SELECTION + CONVERGENCE
# =========================================================================


class TestWinnerSelection:
    """Tests 35–45: deterministic winner selection and convergence."""

    @pytest.fixture()
    def cfg(self) -> UtilityConfig:
        return UtilityConfig()

    def test_highest_utility_wins(self, cfg):
        """35. Higher effective utility → rank 1."""
        bids = [
            _bid(robot_id="amr-01", task_priority=0.9),
            _bid(robot_id="amr-02", task_priority=0.2),
        ]
        ranking = compute_ranking(bids, cfg)
        assert ranking[0].robot_id == "amr-01"
        assert ranking[0].rank == 1

    def test_lower_utility_loses(self, cfg):
        """36. Lower utility → higher rank number."""
        bids = [
            _bid(robot_id="amr-01", task_priority=0.2),
            _bid(robot_id="amr-02", task_priority=0.9),
        ]
        ranking = compute_ranking(bids, cfg)
        assert ranking[0].robot_id == "amr-02"
        assert ranking[1].robot_id == "amr-01"

    def test_equal_utility_deterministic_tiebreak(self, cfg):
        """37. Equal utility → deterministic tie-break by robot_id."""
        bids = [
            _bid(robot_id="amr-02", task_priority=0.5),
            _bid(robot_id="amr-01", task_priority=0.5),
        ]
        ranking = compute_ranking(bids, cfg)
        # Both have same utility; lower robot_id wins tie-break
        assert ranking[0].robot_id == "amr-01"
        assert ranking[1].robot_id == "amr-02"

    def test_n_way_tie(self, cfg):
        """38. N-way tie resolved deterministically."""
        bids = [_bid(robot_id=f"amr-{i:02d}") for i in range(1, 6)]
        ranking = compute_ranking(bids, cfg)
        ids = [r.robot_id for r in ranking]
        assert ids == sorted(ids)  # lexicographic order for ties

    def test_repeated_identical_auction_same_winner(self, cfg):
        """39. Same bid set → same winner every time."""
        bids = [
            _bid(robot_id="amr-01", task_priority=0.7),
            _bid(robot_id="amr-02", task_priority=0.4),
        ]
        winners = [compute_ranking(bids, cfg)[0].robot_id for _ in range(5)]
        assert all(w == "amr-01" for w in winners)

    def test_shuffled_bid_order_same_winner(self, cfg):
        """40. Different input order → same winner."""
        bids_a = [
            _bid(robot_id="amr-01", task_priority=0.6),
            _bid(robot_id="amr-02", task_priority=0.8),
            _bid(robot_id="amr-03", task_priority=0.4),
        ]
        bids_b = [bids_a[2], bids_a[0], bids_a[1]]
        bids_c = [bids_a[1], bids_a[2], bids_a[0]]
        r_a = compute_ranking(bids_a, cfg)
        r_b = compute_ranking(bids_b, cfg)
        r_c = compute_ranking(bids_c, cfg)
        assert r_a[0].robot_id == r_b[0].robot_id == r_c[0].robot_id

    def test_ranking_is_deterministic(self, cfg):
        """41. Full ranking order is deterministic."""
        bids = [
            _bid(robot_id="amr-03", task_priority=0.3),
            _bid(robot_id="amr-01", task_priority=0.9),
            _bid(robot_id="amr-02", task_priority=0.6),
        ]
        r1 = compute_ranking(bids, cfg)
        r2 = compute_ranking(list(reversed(bids)), cfg)
        assert [p.robot_id for p in r1] == [p.robot_id for p in r2]

    def test_convergence_same_bid_set_same_winner(self, cfg):
        """42. Two 'participants' with same bid set → same winner."""
        bids = [
            _bid(robot_id="amr-01", task_priority=0.7),
            _bid(robot_id="amr-02", task_priority=0.4),
        ]
        # Simulate two independent computations
        r_participant_a = compute_ranking(list(bids), cfg)
        r_participant_b = compute_ranking(list(reversed(bids)), cfg)
        assert r_participant_a[0].robot_id == r_participant_b[0].robot_id
        d_a = compute_decision_id("auc-1", 1, r_participant_a)
        d_b = compute_decision_id("auc-1", 1, r_participant_b)
        assert d_a == d_b

    def test_convergence_different_arrival_order(self, cfg):
        """43. Message arrival order doesn't affect outcome."""
        bids = [
            _bid(robot_id="amr-01", task_priority=0.5, waiting_time=30.0),
            _bid(robot_id="amr-02", task_priority=0.5, waiting_time=60.0),
            _bid(robot_id="amr-03", task_priority=0.9, waiting_time=0.0),
        ]
        import itertools
        results = set()
        for perm in itertools.permutations(bids):
            r = compute_ranking(list(perm), cfg)
            results.add(r[0].robot_id)
        assert len(results) == 1  # same winner in all 6 permutations

    def test_incomplete_view_does_not_finalize(self):
        """44. ALL_BIDS_RECEIVED policy blocks close if bids missing."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            close_policy=AuctionClosePolicy.ALL_BIDS_RECEIVED,
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        # Only 1 of 2 bids — should not be ready
        result = eng.try_close_auction("auc-1", current_time=200.0)
        assert result is None
        assert eng.get_auction_status("auc-1") == AuctionStatus.COLLECTING_BIDS

    def test_inconsistent_decisions_detected(self):
        """45. Externally received inconsistent decision is detected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        local_decision = eng.close_auction("auc-1", current_time=50.0)

        # Consistent external decision
        assert eng.validate_external_decision(local_decision) is True

        # Inconsistent: different winner
        fake = AuctionDecision(
            auction_id="auc-1", auction_version=1,
            decision_id="fake_id", winner_id="amr-99",
            status=AuctionStatus.COMMITTED,
        )
        assert eng.validate_external_decision(fake) is False


# =========================================================================
# 10. RESERVATION INTEGRATION
# =========================================================================


class TestReservationIntegration:
    """Tests 53–59: reservation commit via ReservationManager."""

    def test_successful_reservation_commit(self):
        """53. Winning bid → reservation confirmed."""
        eng, rm = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.COMMITTED
        assert decision.reservation_result is not None
        assert decision.reservation_result.success is True

    def test_reservation_conflict(self):
        """54. Pre-existing reservation blocks commit."""
        eng, rm = _engine()
        from app.coordination.reservation import ReservationRequest
        rm.request_reservation(ReservationRequest(
            reservation_id="pre", robot_id="amr-99",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=0.0,
        ))
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.RESERVATION_COMMIT_FAILED
        assert decision.reservation_result.success is False

    def test_reservation_race(self):
        """55. Resource taken between winner selection and commit."""
        eng, rm = _engine()
        eng.create_auction(_auction_req(auction_id="auc-race"))
        eng.submit_bid(_bid(auction_id="auc-race", robot_id="amr-01",
                            task_priority=0.9))
        eng.submit_bid(_bid(auction_id="auc-race", robot_id="amr-02",
                            task_priority=0.3))

        # Another robot grabs the resource just before commit
        from app.coordination.reservation import ReservationRequest
        rm.request_reservation(ReservationRequest(
            reservation_id="snipe", robot_id="amr-50",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=5.0,
        ))

        decision = eng.close_auction("auc-race", current_time=50.0)
        assert decision.status == AuctionStatus.RESERVATION_COMMIT_FAILED
        # No false PROCEED
        assert decision.winner_id == "amr-01"
        assert decision.ranking[0].outcome == ParticipantOutcome.PROCEED

    def test_no_false_success_after_commit_failure(self):
        """56. RESERVATION_COMMIT_FAILED is the final status."""
        eng, rm = _engine()
        from app.coordination.reservation import ReservationRequest
        rm.request_reservation(ReservationRequest(
            reservation_id="blocker", robot_id="amr-99",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=0.0,
        ))
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.RESERVATION_COMMIT_FAILED
        # Repeated close returns same failed decision
        decision2 = eng.close_auction("auc-1", current_time=60.0)
        assert decision2.status == AuctionStatus.RESERVATION_COMMIT_FAILED

    def test_retry_after_failed_commit(self):
        """57. New auction version after failure can succeed."""
        eng, rm = _engine()
        from app.coordination.reservation import ReservationRequest
        rm.request_reservation(ReservationRequest(
            reservation_id="blocker", robot_id="amr-99",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=0.0,
        ))
        eng.create_auction(_auction_req(auction_version=1))
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        d1 = eng.close_auction("auc-1", current_time=50.0)
        assert d1.status == AuctionStatus.RESERVATION_COMMIT_FAILED

        # Remove blocker, retry with new version
        rm.release_reservation("blocker", "amr-99")
        eng.create_auction(_auction_req(auction_version=2))
        eng.submit_bid(_bid(robot_id="amr-01", auction_version=2))
        eng.submit_bid(_bid(robot_id="amr-02", auction_version=2))
        d2 = eng.close_auction("auc-1", current_time=60.0)
        assert d2.status == AuctionStatus.COMMITTED

    def test_duplicate_commit_does_not_duplicate_reservation(self):
        """58. Idempotent close doesn't create duplicate reservation."""
        eng, rm = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        d1 = eng.close_auction("auc-1", current_time=50.0)
        d2 = eng.close_auction("auc-1", current_time=60.0)
        assert d1.decision_id == d2.decision_id
        # Only one reservation exists
        reservations = rm.get_robot_reservations("amr-01")
        auction_res = [
            r for r in reservations
            if r.reservation_id.startswith("auction_auc-1")
        ]
        assert len(auction_res) == 1

    def test_path_version_mismatch_in_reservation(self):
        """59. Reservation carries the correct path_version from bid."""
        eng, rm = _engine()
        eng.create_auction(_auction_req(
            path_versions={"amr-01": 3, "amr-02": 2},
        ))
        eng.submit_bid(_bid(robot_id="amr-01", path_version=3,
                            task_priority=0.9))
        eng.submit_bid(_bid(robot_id="amr-02", path_version=2,
                            task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.COMMITTED
        r = rm.get_reservation(decision.reservation_result.reservations[0].reservation_id)
        assert r.path_version == 3


# =========================================================================
# 11. DECISION IDEMPOTENCY
# =========================================================================


class TestDecisionIdempotency:
    """Tests 60–62: decision idempotency."""

    def test_duplicate_identical_decision(self):
        """60. Repeated close → same decision returned."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        d1 = eng.close_auction("auc-1", current_time=50.0)
        d2 = eng.close_auction("auc-1", current_time=60.0)
        assert d1.decision_id == d2.decision_id
        assert d1.winner_id == d2.winner_id

    def test_conflicting_duplicate_decision_detected(self):
        """61. External decision with different winner detected."""
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        eng.close_auction("auc-1", current_time=50.0)
        fake = AuctionDecision(
            auction_id="auc-1", auction_version=1,
            decision_id="wrong-id", winner_id="amr-02",
            status=AuctionStatus.COMMITTED,
        )
        assert eng.validate_external_decision(fake) is False

    def test_stale_decision(self):
        """62. Stale auction version decision doesn't match."""
        eng, _ = _engine()
        eng.create_auction(_auction_req(auction_version=1))
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        d1 = eng.close_auction("auc-1", current_time=50.0)

        # New version auction
        eng.create_auction(_auction_req(auction_version=2))
        eng.submit_bid(_bid(robot_id="amr-01", auction_version=2,
                            task_priority=0.3))
        eng.submit_bid(_bid(robot_id="amr-02", auction_version=2,
                            task_priority=0.9))
        d2 = eng.close_auction("auc-1", current_time=60.0)
        assert d2.winner_id != d1.winner_id or d2.decision_id != d1.decision_id


# =========================================================================
# 12. ACTION RECOMMENDATIONS
# =========================================================================


class TestActionRecommendations:
    """Tests 63–65: participant outcome assignments."""

    def test_winner_gets_proceed(self):
        """63. Rank 1 gets PROCEED."""
        cfg = UtilityConfig()
        bids = [
            _bid(robot_id="amr-01", task_priority=0.9),
            _bid(robot_id="amr-02", task_priority=0.3),
        ]
        ranking = compute_ranking(bids, cfg)
        assert ranking[0].outcome == ParticipantOutcome.PROCEED

    def test_loser_gets_wait_or_yield(self):
        """64. Losers get WAIT (rank 2) or YIELD (rank 3+)."""
        cfg = UtilityConfig()
        bids = [
            _bid(robot_id="amr-01", task_priority=0.9),
            _bid(robot_id="amr-02", task_priority=0.5),
            _bid(robot_id="amr-03", task_priority=0.2),
        ]
        ranking = compute_ranking(bids, cfg)
        assert ranking[0].outcome == ParticipantOutcome.PROCEED
        assert ranking[1].outcome == ParticipantOutcome.WAIT
        assert ranking[2].outcome == ParticipantOutcome.YIELD

    def test_recommendations_include_context(self):
        """65. Recommendations include utility breakdown context."""
        cfg = UtilityConfig()
        bids = [
            _bid(robot_id="amr-01", task_priority=0.7),
            _bid(robot_id="amr-02", task_priority=0.4),
        ]
        ranking = compute_ranking(bids, cfg)
        for rp in ranking:
            assert rp.utility_breakdown is not None
            assert rp.utility_breakdown.effective_utility >= 0.0
            assert rp.robot_id != ""
            assert rp.rank >= 1


# =========================================================================
# 13. MULTI-ROBOT SCENARIOS
# =========================================================================


class TestMultiRobotScenarios:
    """Tests 66–70: multi-robot contention scenarios."""

    def test_three_way_intersection(self):
        """66. 3-robot intersection contention."""
        eng, _ = _engine()
        pids = ["amr-01", "amr-02", "amr-03"]
        eng.create_auction(_auction_req(participant_ids=pids))
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.5))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-03", task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.COMMITTED
        assert decision.winner_id == "amr-02"
        assert len(decision.ranking) == 3

    def test_four_way_intersection(self):
        """67. 4-robot intersection."""
        eng, _ = _engine()
        pids = [f"amr-{i:02d}" for i in range(1, 5)]
        eng.create_auction(_auction_req(participant_ids=pids))
        priorities = [0.4, 0.9, 0.2, 0.7]
        for pid, p in zip(pids, priorities):
            eng.submit_bid(_bid(robot_id=pid, task_priority=p))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.winner_id == "amr-02"  # highest priority

    def test_five_robot_bottleneck(self):
        """68. 5-robot bottleneck with varied priorities."""
        eng, _ = _engine()
        pids = [f"amr-{i:02d}" for i in range(1, 6)]
        eng.create_auction(_auction_req(participant_ids=pids))
        for i, pid in enumerate(pids):
            eng.submit_bid(_bid(
                robot_id=pid,
                task_priority=0.2 * (i + 1) / 5,
                waiting_time=float(i * 10),
            ))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.status == AuctionStatus.COMMITTED
        assert len(decision.ranking) == 5

    def test_repeated_contention_with_aging(self):
        """69. Repeated contention — waiting robot gains utility."""
        cfg = UtilityConfig()
        # Round 1: equal priority, no wait
        bids_r1 = [
            _bid(robot_id="amr-01", task_priority=0.5, waiting_time=0.0),
            _bid(robot_id="amr-02", task_priority=0.5, waiting_time=0.0),
        ]
        r1 = compute_ranking(bids_r1, cfg)
        # amr-01 wins on tie-break (lower ID)
        assert r1[0].robot_id == "amr-01"

        # Round 2: amr-02 has been waiting
        bids_r2 = [
            _bid(robot_id="amr-01", task_priority=0.5, waiting_time=0.0),
            _bid(robot_id="amr-02", task_priority=0.5, waiting_time=120.0),
        ]
        r2 = compute_ranking(bids_r2, cfg)
        # amr-02 should now win due to aging
        assert r2[0].robot_id == "amr-02"

    def test_repeated_contention_fairer_ordering(self):
        """70. Sustained waiting produces fairer long-term ordering."""
        cfg = UtilityConfig()
        # Robot with lower priority but very long wait beats fresh robot
        bids = [
            _bid(robot_id="amr-fresh", task_priority=0.6, waiting_time=0.0),
            _bid(robot_id="amr-starved", task_priority=0.4, waiting_time=300.0),
        ]
        ranking = compute_ranking(bids, cfg)
        # Starved robot's aging overcomes priority gap
        assert ranking[0].robot_id == "amr-starved"


# =========================================================================
# 14. INTEGRATION
# =========================================================================


class TestIntegration:
    """Tests 71–74: cross-module integration."""

    def test_conflict_result_generates_auction_request(self):
        """71. ConflictResult → AuctionRequest via helper."""
        conflict = ConflictResult(
            robot_a_id="amr-01",
            robot_b_id="amr-02",
            conflict_type=ConflictType.VERTEX,
            location=Position(x=5.0, y=10.0),
            time_window_start=10.0,
            time_window_end=20.0,
            min_distance=0.5,
            robot_a_path_version=3,
            robot_b_path_version=2,
        )
        req = create_auction_from_conflict(
            conflict,
            auction_id="auc-from-conflict",
            resource_id="intersection-5-10",
            created_at=5.0,
            deadline=50.0,
        )
        assert req.auction_id == "auc-from-conflict"
        assert set(req.participant_ids) == {"amr-01", "amr-02"}
        assert req.time_window_start == 10.0
        assert req.time_window_end == 20.0
        assert req.path_versions["amr-01"] == 3
        assert req.path_versions["amr-02"] == 2

    def test_auction_uses_reservation_manager_api(self):
        """72. Auction engine calls ReservationManager.request_reservation."""
        eng, rm = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=0.8))
        eng.submit_bid(_bid(robot_id="amr-02", task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        assert decision.reservation_result is not None
        # Reservation actually exists in the manager
        r = rm.get_reservation(
            decision.reservation_result.reservations[0].reservation_id,
        )
        assert r is not None
        assert r.robot_id == "amr-01"

    def test_reservation_manager_remains_authority(self):
        """73. ReservationManager is the authority; auction doesn't bypass."""
        eng, rm = _engine()
        from app.coordination.reservation import ReservationRequest
        # Block the resource
        rm.request_reservation(ReservationRequest(
            reservation_id="authority-test", robot_id="amr-99",
            resource_id="corridor-A1", start_time=10.0, end_time=20.0,
            path_version=1, created_at=0.0,
        ))
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01", task_priority=1.0))
        eng.submit_bid(_bid(robot_id="amr-02"))
        decision = eng.close_auction("auc-1", current_time=50.0)
        # Even with highest priority, the auction cannot force a reservation
        assert decision.status == AuctionStatus.RESERVATION_COMMIT_FAILED

    def test_path_version_propagation(self):
        """74. Path version flows from bid → reservation."""
        eng, rm = _engine()
        eng.create_auction(_auction_req(
            path_versions={"amr-01": 5, "amr-02": 3},
        ))
        eng.submit_bid(_bid(robot_id="amr-01", path_version=5,
                            task_priority=0.9))
        eng.submit_bid(_bid(robot_id="amr-02", path_version=3,
                            task_priority=0.3))
        decision = eng.close_auction("auc-1", current_time=50.0)
        r = rm.get_reservation(
            decision.reservation_result.reservations[0].reservation_id,
        )
        assert r.path_version == 5


# =========================================================================
# 15. ENGINE QUERIES + CLEAR
# =========================================================================


class TestEngineQueries:
    """Engine query and clear operations."""

    def test_get_auction_status(self):
        eng, _ = _engine()
        assert eng.get_auction_status("nonexistent") is None
        eng.create_auction(_auction_req())
        assert eng.get_auction_status("auc-1") == AuctionStatus.COLLECTING_BIDS

    def test_get_collected_bids(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.submit_bid(_bid(robot_id="amr-01"))
        bids = eng.get_collected_bids("auc-1")
        assert len(bids) == 1

    def test_clear(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        eng.clear()
        assert eng.get_auction_status("auc-1") is None

    def test_try_close_returns_none_when_not_ready(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            close_policy=AuctionClosePolicy.ALL_BIDS_RECEIVED,
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        assert eng.try_close_auction("auc-1", current_time=200.0) is None

    def test_try_close_returns_decision_when_ready(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req(
            close_policy=AuctionClosePolicy.ALL_BIDS_RECEIVED,
        ))
        eng.submit_bid(_bid(robot_id="amr-01"))
        eng.submit_bid(_bid(robot_id="amr-02"))
        d = eng.try_close_auction("auc-1", current_time=50.0)
        assert d is not None
        assert d.status in (AuctionStatus.COMMITTED, AuctionStatus.RESERVATION_COMMIT_FAILED)

    def test_idempotent_create_auction(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req())
        # Same version → idempotent
        eng.create_auction(_auction_req())
        assert eng.get_auction_status("auc-1") == AuctionStatus.COLLECTING_BIDS

    def test_create_auction_version_conflict_raises(self):
        eng, _ = _engine()
        eng.create_auction(_auction_req(auction_version=2))
        with pytest.raises(ValueError):
            eng.create_auction(_auction_req(auction_version=1))

    def test_close_nonexistent_raises(self):
        eng, _ = _engine()
        with pytest.raises(ValueError):
            eng.close_auction("ghost", current_time=50.0)
