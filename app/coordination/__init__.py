"""
SWARMOS Coordination Package — Public API

Re-exports the canonical contracts so that other subsystems can do:

    from app.coordination import AMRState, CoordinationMessage, ...
"""

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
from app.coordination.transport import TransportInterface
from app.coordination.peer_registry import PeerStateRegistry
from app.coordination.intent_registry import IntentRegistry
from app.coordination.conflict import (
    ConflictDetectionConfig,
    ConflictResult,
    ConflictType,
    TimedSegment,
    build_timed_path,
    detect_all_conflicts,
    detect_pairwise_conflicts,
)
from app.coordination.reservation import (
    Reservation,
    ReservationConflictInfo,
    ReservationManager,
    ReservationRequest,
    ReservationResult,
    ReservationStatus,
    is_valid_transition,
)
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
from app.coordination.radio import (
    CONFIRM_TIMEOUT_S,
    HEARTBEAT_HZ,
    HEARTBEAT_PERIOD_S,
    HEARTBEAT_TIMEOUT_S,
    LINK_DEGRADED,
    LINK_PERFECT,
    LINK_SEVERE,
    R_COMM_M,
    BoundedRadio,
    FailureDetector,
    FailureEvent,
    LinkProfile,
    PeerHealth,
    RadioStats,
)

__all__ = [

    # Models (Step 1)
    "AMRState",
    "MovementIntent",
    "Position",
    "RobotStatus",
    # Messages (Step 1)
    "CoordinationMessage",
    "MessageType",
    "create_path_intent_message",
    "create_robot_state_message",
    # Transport (Step 1)
    "TransportInterface",
    # Peer Registry (Step 2)
    "PeerStateRegistry",
    # Intent Registry (Step 2)
    "IntentRegistry",
    # Conflict Detection (Step 2)
    "ConflictDetectionConfig",
    "ConflictResult",
    "ConflictType",
    "TimedSegment",
    "build_timed_path",
    "detect_all_conflicts",
    "detect_pairwise_conflicts",
    # Reservation (Step 3)
    "Reservation",
    "ReservationConflictInfo",
    "ReservationManager",
    "ReservationRequest",
    "ReservationResult",
    "ReservationStatus",
    "is_valid_transition",
    # Auction / Negotiation (Step 4)
    "AuctionBid",
    "AuctionClosePolicy",
    "AuctionDecision",
    "AuctionRequest",
    "AuctionStatus",
    "BidResult",
    "NegotiationEngine",
    "ParticipantOutcome",
    "RankedParticipant",
    "UtilityBreakdown",
    "UtilityConfig",
    "calculate_aging",
    "calculate_utility",
    "compute_decision_id",
    "compute_ranking",
    "create_auction_from_conflict",
    "is_valid_auction_transition",
    # Bounded radio / failure detection (Step 4B)
    "BoundedRadio",
    "CONFIRM_TIMEOUT_S",
    "FailureDetector",
    "FailureEvent",
    "HEARTBEAT_HZ",
    "HEARTBEAT_PERIOD_S",
    "HEARTBEAT_TIMEOUT_S",
    "LINK_DEGRADED",
    "LINK_PERFECT",
    "LINK_SEVERE",
    "LinkProfile",
    "PeerHealth",
    "RadioStats",
    "R_COMM_M",
]


# File contains AI-generated response based on internal company sources
