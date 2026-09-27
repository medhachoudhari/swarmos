# Step 4A — Learning Map

A deep technical study guide for defending the SWARMOS Step 4A implementation
in SIH judging, technical interviews, project reviews, and architecture
discussions.

Based on the actual code in `app/coordination/auction.py` (1004 lines),
`tests/test_auction.py` (1388 lines, 105 tests), and all related modules.

**How to use this document**: Follow the flow from Architecture → Auction →
Utility → Winner Selection → Reservation → Tests → Failure Cases. Each
section answers the 15 questions you need for a technical defense.

---

## ARCHITECTURE

### Module Position in SWARMOS

```
ConflictDetector (Step 2 — conflict.py)
       ↓
ConflictResult
       ↓
create_auction_from_conflict()  ← bridge
       ↓
AuctionRequest
       ↓
NegotiationEngine               ← this module (auction.py)
  ├─ submit_bid() × N
  ├─ close_auction()
  │    ├─ compute_ranking()      ← pure function
  │    ├─ compute_decision_id()  ← pure function
  │    └─ ReservationManager.request_reservation()  ← Step 3
  └─ AuctionDecision
```

### Dependency Graph (Imports Only)

```
models.py ←── auction.py (imports _require_finite, _require_non_whitespace)
conflict.py ←── auction.py (imports ConflictResult)
reservation.py ←── auction.py (imports ReservationManager, ReservationRequest, ReservationResult)
```

No circular dependencies. auction.py does NOT import from messages.py,
transport.py, peer_registry.py, or intent_registry.py. This is correct:
auction logic is transport-agnostic.

### What This Module Does NOT Do

- Does NOT move robots
- Does NOT call A*
- Does NOT implement deadlock detection
- Does NOT run failure recovery
- Does NOT use networking
- Does NOT access wall-clock time
- Does NOT use randomness

---

## COORDINATION FLOW

### End-to-End Right-of-Way Resolution

```
1. Two robots' paths conflict at corridor-A1, time [10, 20)
   → ConflictDetector produces ConflictResult

2. Coordination loop (future) calls:
   create_auction_from_conflict(conflict, auction_id="auc-1",
                                resource_id="corridor-A1", ...)
   → produces AuctionRequest

3. NegotiationEngine.create_auction(request) → registers session
   Status: COLLECTING_BIDS

4. Each robot submits a bid:
   engine.submit_bid(AuctionBid(robot_id="amr-01", task_priority=0.8, ...))
   engine.submit_bid(AuctionBid(robot_id="amr-02", task_priority=0.3, ...))

5. engine.is_ready_to_close("auc-1", current_time=50.0)
   → True (both bids received, or deadline passed)

6. engine.close_auction("auc-1", current_time=50.0)
   a. COLLECTING_BIDS → BIDS_CLOSED
   b. compute_ranking() → amr-01 rank 1, amr-02 rank 2
   c. BIDS_CLOSED → WINNER_SELECTED
   d. Create ReservationRequest for amr-01 at corridor-A1 [10, 20)
   e. WINNER_SELECTED → RESERVATION_COMMITTING
   f. ReservationManager.request_reservation() → success
   g. RESERVATION_COMMITTING → COMMITTED

7. AuctionDecision returned:
   winner_id="amr-01", status=COMMITTED
   ranking: [amr-01: PROCEED, amr-02: WAIT]
```

### What Each Robot Learns

| Robot | Outcome | Action |
|---|---|---|
| amr-01 (winner) | PROCEED | Continue on planned path through corridor-A1 |
| amr-02 (loser, rank 2) | WAIT | Hold position until corridor-A1 is free |
| amr-03+ (rank 3+) | YIELD | May need to reroute |

---

## AUCTION

### AuctionRequest — What It Contains and Why

**File**: auction.py L314–404

```python
class AuctionRequest(BaseModel):
    auction_id: str          # Unique ID for this auction
    auction_version: int     # Incremented on retry (stale detection)
    requester_id: str        # Who triggered the auction
    participant_ids: list[str]  # Sorted, deduplicated — exactly who competes
    resource_id: str         # What resource is contested (e.g., "corridor-A1")
    time_window_start: float # When the conflict starts
    time_window_end: float   # When the conflict ends
    source_conflict_id: str | None  # Traceability to ConflictResult
    path_versions: dict[str, int]   # Expected path version per robot
    created_at: float        # Caller-supplied timestamp
    deadline: float          # When bidding closes
    close_policy: AuctionClosePolicy  # How to close (ALL/DEADLINE/ALL_OR_DEADLINE)
```

**Why `participant_ids` is sorted**: Determinism. If two participants construct
the same request with different input order, the sorted list ensures identical
content.

**Why `path_versions`**: Stale bid detection. If amr-01's path changed to
version 4, a bid with path_version=3 is stale and rejected.

**Judge question**: "Why is the participant set explicit instead of
auto-discovered?"

**Answer**: Auto-discovery requires fleet-wide communication (O(N)). Explicit
sets limit auction scope to the 2-5 robots actually in conflict, as
identified by ConflictDetector. This is essential for scalability.

---

### AuctionBid — What a Robot Submits

**File**: auction.py L407–463

```python
class AuctionBid(BaseModel):
    auction_id: str
    auction_version: int
    robot_id: str
    path_version: int

    # Utility inputs — the "arguments" to the utility function
    task_priority: float      # [0, 1] — how important is this task?
    deadline_urgency: float   # [0, 1] — how close to deadline?
    battery_urgency: float    # [0, 1] — how urgently does this robot need to charge?
    estimated_arrival: float  # seconds — how soon does this robot arrive?
    remaining_distance: float # metres — how far does this robot have to go?
    waiting_time: float       # seconds — how long has this robot been waiting?

    bid_timestamp: float      # when was this bid created?
    bid_sequence: int         # monotonic sequence for dedup/supersession
```

**Critical design choice**: The bid does NOT carry a pre-computed utility.
Utility is always calculated by `calculate_utility(bid, config)` using the
shared `UtilityConfig`. This ensures all participants use the same formula.

**Judge question**: "Why not let each robot compute its own utility?"

**Answer**: If each robot computed its own utility with its own weights,
two robots would disagree on who should win. By using raw inputs + shared
config + shared formula, every participant independently arrives at the same
ranking. This is the convergence property.

---

### NegotiationEngine — The Lifecycle Manager

**File**: auction.py L662–1004

1. **What problem does it solve?**
   Manages the lifecycle of multiple concurrent auctions: creation, bid
   collection, validation, closing, winner selection, and reservation
   commitment.

2. **Why does it exist?**
   The pure functions (compute_ranking, calculate_utility) are stateless.
   Something needs to manage the stateful auction sessions, validate bids,
   enforce close policies, and coordinate with ReservationManager.

3. **Inputs**: ReservationManager (required), UtilityConfig (optional).

4. **Outputs**: AuctionDecision via close_auction/try_close_auction.

5. **State owned**:
   - `_sessions: dict[str, _AuctionSession]` — active auctions
   - `_committed_decisions: dict[str, AuctionDecision]` — idempotency cache

6. **Dependencies**: ReservationManager, UtilityConfig, compute_ranking.

7. **Important invariants**:
   - Only one active session per auction_id at a time
   - Bids only accepted during COLLECTING_BIDS
   - close_auction is idempotent (returns cached decision)
   - State transitions follow the explicit state machine

8. **Main algorithm**: Sequential validation → pure ranking → reservation
   delegation.

9. **Simpler alternative**: A single function that takes all bids and returns
   a winner. No session management.

10. **More advanced alternative**: Distributed engine with timeout management,
    automatic re-auction, and cross-node state synchronization.

11. **Why current approach is reasonable**: Session management is needed for
    incremental bid collection. Pure functions handle the core algorithm.
    The engine adds lifecycle control without algorithmic complexity.

12. **What can go wrong**:
    - `_committed_decisions` grows unboundedly (LOW risk for SIH)
    - Not thread-safe (documented)
    - No automatic timeout (DEFER to coordination loop)

13. **Which tests protect it**: TestAuctionStateMachine (8 tests),
    TestBidCollection (14 tests), TestReservationIntegration (7 tests),
    TestDecisionIdempotency (3 tests), TestEngineQueries (8 tests).

14. **Future consumer**: Coordination loop, per-robot agent, edge coordinator.

15. **Likely judge questions**:
    - "Is NegotiationEngine a god class?" → No, 13 methods, each small.
      Delegates utility to pure functions and reservation to ReservationManager.
    - "How does it scale?" → O(n log n) for ranking where n ≈ 2–5.
      Session management is O(1) per operation.
    - "Is it thread-safe?" → No, documented. Single-threaded by design.

---

## UTILITY

### calculate_utility(bid, config) → UtilityBreakdown

**File**: auction.py L263–307

1. **What problem does it solve?**
   Converts raw bid inputs into a single comparable score for ranking.

2. **Why does it exist?**
   Right-of-way decisions require comparing multiple dimensions (priority,
   urgency, battery, wait time, distance, arrival). A scalar utility
   reduces multi-dimensional comparison to simple sorting.

3. **Inputs**: AuctionBid (raw values), UtilityConfig (weights + normalization).

4. **Outputs**: UtilityBreakdown (6 weighted components + effective_utility).

5. **State owned**: None — pure function.

6. **Dependencies**: calculate_aging (for the aging component).

7. **Important invariants**:
   - Each component ∈ [0, weight]
   - effective_utility = sum of all 6 components
   - Same inputs → same output (deterministic)
   - No hidden dependencies (no time.time(), no random)

8. **Main algorithm**:
   ```
   For each factor:
     raw = clamp(input, 0, 1)        # normalize
     component = raw × weight          # apply weight
   effective_utility = sum(components)
   ```
   For delay and distance, the raw value is inverted (1 − normalized)
   because shorter/closer is better.

9. **Simpler alternative**: Just compare task_priority directly.

10. **More advanced alternative**: ML-trained multi-objective utility.

11. **Why current approach is reasonable**: Weighted sum is the standard
    approach in multi-attribute decision theory. It's explainable, testable,
    and configurable.

12. **What can go wrong**: Weights misconfigured → unintuitive rankings.
    Mitigated by sensible defaults and UtilityConfig being explicit.

13. **Which tests protect it**: TestUtilityCalculation (11 tests) — verifies
    monotonicity, normalization, bounds, component sum, configurability.

14. **Future consumer**: compute_ranking (and transitively, any participant
    in a distributed auction).

15. **Likely judge questions**:
    - "How do you know the weights are correct?" → We don't claim optimality.
      Defaults are documented starting points. UtilityConfig is configurable.
      Field testing would tune them.
    - "Can priority override everything?" → With default weight 0.30, max
      priority contributes 0.30. All other factors at max contribute 0.70.
      Priority alone cannot override the combined rest.
    - "What about fairness?" → The aging component (weight 0.15) provides
      anti-starvation. A robot waiting 2 half-lives (120s) gets aging ≈ 0.75
      × 0.15 = 0.11, which is enough to overcome moderate priority gaps.

---

### calculate_aging(waiting_time, config) → float

**File**: auction.py L237–260

**Formula**: `1 - exp(-t × ln2 / half_life)`

**Properties table**:

| Waiting Time | Aging Value | Weighted (w=0.15) |
|---|---|---|
| 0 seconds | 0.000 | 0.000 |
| 30 seconds | 0.293 | 0.044 |
| 60 seconds (half-life) | 0.500 | 0.075 |
| 120 seconds | 0.750 | 0.113 |
| 300 seconds | 0.969 | 0.145 |
| 600 seconds | 0.999 | 0.150 |

**Why exponential, not linear**: Linear aging `min(1, t/max)` has a cliff
at the cap — equal weight per second until max, then flat. Exponential
saturation gives diminishing returns: the first 60 seconds matter most.

**Judge question**: "Can a very long wait override a much higher-priority task?"

**Answer**: Yes, by design. With defaults, a robot with priority 0.4 and
waiting_time=300s has aging utility ≈ 0.145. A fresh robot with priority 0.6
has only 0.06 more priority utility (0.18 vs 0.12). The starved robot wins.
This IS the anti-starvation mechanism. For truly critical tasks, use
task_priority near 1.0 where the 0.30 weight dominates.

---

## WINNER SELECTION

### compute_ranking(bids, config) → list[RankedParticipant]

**File**: auction.py L532–585

1. **What problem does it solve?**
   Deterministic, order-independent ranking of auction participants.

2. **Why does it exist?**
   In a decentralized system, each participant must independently compute
   the same winner. A pure function with deterministic sorting guarantees
   convergence.

3. **Inputs**: list of AuctionBid, UtilityConfig.

4. **Outputs**: list of RankedParticipant (sorted, rank 1 = winner).

5. **State owned**: None — pure function.

6. **Dependencies**: calculate_utility.

7. **Important invariants**:
   - Input order does NOT affect output
   - Same inputs → same output on any machine
   - Rank 1 → PROCEED, Rank 2 → WAIT, Rank 3+ → YIELD

8. **Main algorithm**:
   ```
   1. For each bid: breakdown = calculate_utility(bid, config)
   2. Sort by: (-effective_utility, -aging_component, -deadline_component, +robot_id)
   3. Assign outcomes: rank 1 → PROCEED, rank 2 → WAIT, rank 3+ → YIELD
   ```

9. **Simpler alternative**: Just pick the highest priority robot.

10. **More advanced alternative**: Multi-round negotiation with bid adjustment.

11. **Why current approach is reasonable**: Single-round, deterministic,
    pure. No negotiation overhead. Converges without message exchange
    (given identical inputs).

12. **What can go wrong**:
    - Duplicate robot_ids in input → two rankings for same robot.
      Prevented by NegotiationEngine.submit_bid dedup.
    - Floating-point ULP differences across platforms → extremely unlikely
      ranking divergence.

13. **Which tests protect it**: TestWinnerSelection (11 tests) including
    permutation tests, tie-break tests, convergence tests.

14. **Future consumer**: NegotiationEngine.close_auction, any distributed
    participant.

15. **Likely judge questions**:
    - "Why is this a module-level function, not a method?" → So that any
      participant can call it independently. Methods on NegotiationEngine
      would require an engine instance. Pure functions require only data.
    - "Is the tie-breaking fair?" → Not per-round (favors lower robot_id).
      But aging provides dynamic fairness over time. See aging analysis.

### Tie-Break Hierarchy (Memorize This)

```
Level 1: Higher effective_utility wins
Level 2: Higher aging_component wins (longer wait → favored)
Level 3: Higher deadline_component wins (more urgent → favored)
Level 4: Lower robot_id wins (lexicographic — deterministic, stable)
```

**Why this order**: Utility is the primary ranking. For ties, aging favors
fairness (longest-waiting robot wins). Then deadline favors urgency. Finally,
robot_id is a deterministic, arbitrary tiebreaker.

---

### compute_decision_id(auction_id, version, ranked) → str

**File**: auction.py L588–601

**Format**: `"auc-1_v1_amr-01:1|amr-02:2"`

**Why not UUID**: Two participants independently computing the same ranking
must produce the same decision_id. UUIDs are random. This deterministic ID
enables split-brain detection: if participant A's decision_id ≠ participant
B's, something is wrong.

**Judge question**: "What if the IDs get very long?"

**Answer**: For 2–5 participants (typical local conflict), IDs are ~50
characters. For 10+ participants, IDs grow proportionally. Not a practical
concern.

---

## RESERVATION INTERACTION

### How Auction Commits a Reservation

**File**: auction.py L904–920

```python
res_req = ReservationRequest(
    reservation_id=f"auction_{req.auction_id}_v{req.auction_version}_{winner.robot_id}",
    robot_id=winner.robot_id,
    resource_id=req.resource_id,
    start_time=req.time_window_start,
    end_time=req.time_window_end,
    path_version=winner_bid.path_version,
    created_at=current_time,
    source_conflict_id=req.source_conflict_id,
)
res_result = self._rm.request_reservation(res_req)
```

**Key design point**: The auction module creates a `ReservationRequest` and
calls `ReservationManager.request_reservation()`. It does NOT:
- Check for overlapping reservations itself
- Manage reservation state
- Implement overlap logic

The `ReservationManager` is the authority. If it rejects, the auction gets
RESERVATION_COMMIT_FAILED. The auction does NOT override the reservation
system.

**Judge question**: "What if another robot grabs the resource between winner
selection and reservation commit?"

**Answer**: This is the reservation race scenario. The `ReservationManager`
atomically checks and confirms. If the resource was taken between ranking and
commit, `request_reservation()` returns failure. The auction status becomes
RESERVATION_COMMIT_FAILED. The winner's PROCEED recommendation is issued
(based on ranking) but the reservation is not granted. The coordination loop
(future) would trigger a re-auction with a new version.

**Test coverage**: test_reservation_race (L966–987) explicitly tests this.

---

## STATE / MESSAGE FLOW

### Auction State Machine

```
COLLECTING_BIDS ──→ BIDS_CLOSED ──→ WINNER_SELECTED ──→ RESERVATION_COMMITTING
        │                  │                                    │
        │                  ↓                                    ├──→ COMMITTED (terminal)
        │            NO_VALID_BIDS (terminal)                   │
        │                                                       └──→ RESERVATION_COMMIT_FAILED (terminal)
        ├──→ NO_VALID_BIDS (terminal, if no bids at close)
        ├──→ EXPIRED (terminal)
        └──→ ABORTED (terminal)
```

**Terminal states**: COMMITTED, NO_VALID_BIDS, EXPIRED, RESERVATION_COMMIT_FAILED, ABORTED.
No transitions out of terminal states.

### Bid Validation Flow (submit_bid)

```
1. Auction exists? ── NO → rejected "not found"
2. Status == COLLECTING_BIDS? ── NO → rejected "not accepting bids"
3. auction_version matches? ── NO → rejected "version mismatch"
4. robot_id in participant_ids? ── NO → rejected "not in participant set"
5. path_version >= expected? ── NO → rejected "stale path_version"
6. Duplicate bid? ──YES, identical → accepted "idempotent"
                  ──YES, same seq, different → rejected "conflicting"
                  ──YES, older seq → rejected "stale sequence"
7. → Accepted, stored in session
```

### Close Policy Evaluation

```
ALL_BIDS_RECEIVED: len(bids) >= len(participant_ids)
DEADLINE:          current_time >= request.deadline
ALL_OR_DEADLINE:   either of the above
```

---

## TESTS

### Test Organization (15 Classes, 105 Tests)

| Class | Tests | What It Covers |
|---|---|---|
| TestAuctionRequestContract | 9 | Request model validation: IDs, versions, times, participants, serialization |
| TestAuctionBidContract | 8 | Bid model validation: IDs, bounds, non-finite, serialization |
| TestAuctionDecisionContract | 5 | Decision model validation: IDs, versions, winner representation |
| TestUtilityCalculation | 11 | Utility formula: determinism, component contributions, normalization, bounds |
| TestAgingFunction | 6 | Aging curve: zero, negative, monotonic, bounded, half-life, determinism |
| TestDeterminism | 2 | Same inputs → same outputs, serialized round-trip |
| TestAuctionStateMachine | 8 | State transitions: valid, invalid, expiration, abort |
| TestBidCollection | 14 | Bid acceptance: valid, duplicate, stale, non-participant, policies |
| TestWinnerSelection | 11 | Ranking: utility order, ties, N-way, convergence, permutations |
| TestReservationIntegration | 7 | Commit: success, conflict, race, retry, idempotency, path version |
| TestDecisionIdempotency | 3 | Idempotent close, conflicting decision detection, stale version |
| TestActionRecommendations | 3 | PROCEED/WAIT/YIELD assignment |
| TestMultiRobotScenarios | 5 | 3/4/5-robot contention, aging fairness |
| TestIntegration | 4 | ConflictResult→AuctionRequest, ReservationManager authority |
| TestEngineQueries | 8 | Status queries, clear, try_close, idempotent create |

### Key Tests to Know for Defense

1. **test_convergence_different_arrival_order**: Tests all 6 permutations of
   3 bids — same winner regardless of input order. This proves the convergence
   property.

2. **test_repeated_contention_with_aging**: Two rounds — round 1: equal
   priority, amr-01 wins on tiebreak. Round 2: amr-02 has waiting_time=120s,
   now wins due to aging. This proves anti-starvation works.

3. **test_reservation_race**: Resource grabbed by another robot between
   winner selection and commit → RESERVATION_COMMIT_FAILED. Proves the
   system handles races safely.

4. **test_reservation_manager_remains_authority**: Even with task_priority=1.0,
   if the resource is blocked, the auction cannot force a reservation. Proves
   ReservationManager is the authority.

---

## FAILURE CASES

### What Happens When...

| Scenario | What Happens | Status |
|---|---|---|
| Robot doesn't bid | ALL_OR_DEADLINE policy closes at deadline; missing robot excluded from ranking | PARTIALLY HANDLED |
| Robot bids with stale path | submit_bid rejects: "Stale path_version X < expected Y" | HANDLED |
| Same bid arrives twice | submit_bid returns accepted with "Duplicate bid (idempotent)" | HANDLED |
| Different bid with same sequence | submit_bid rejects: "Bid sequence X <= existing Y" | HANDLED |
| Resource taken before commit | ReservationManager rejects → RESERVATION_COMMIT_FAILED | HANDLED |
| close_auction called twice | Returns cached decision (idempotent) | HANDLED |
| Unknown auction_id | submit_bid: "Auction not found". close_auction: ValueError | HANDLED |
| Version mismatch | submit_bid rejects: "Auction version mismatch" | HANDLED |
| All robots have same priority | Tie-break: aging → deadline → robot_id (deterministic) | HANDLED |
| Network failure | NOT HANDLED (auction.py has no networking — correct boundary) | DEFERRED |
| Heartbeat timeout | NOT HANDLED (belongs to peer registry / coordination loop) | DEFERRED |
| Deadlock | NOT HANDLED (belongs to separate deadlock detection layer) | DEFERRED |

---

## QUICK REFERENCE: Numbers to Memorize

| Metric | Value |
|---|---|
| auction.py lines | 1004 |
| test_auction.py lines | 1388 |
| Test count (Step 4A) | 105 |
| Total test count (all steps) | 296 |
| Public classes | 8 (AuctionRequest, AuctionBid, AuctionDecision, RankedParticipant, BidResult, UtilityConfig, UtilityBreakdown, NegotiationEngine) |
| Public functions | 5 (calculate_aging, calculate_utility, compute_ranking, compute_decision_id, create_auction_from_conflict) |
| Enums | 3 (ParticipantOutcome, AuctionStatus, AuctionClosePolicy) |
| Utility components | 6 (priority, deadline, battery, aging, delay, distance) |
| Default weights | 0.30 + 0.25 + 0.15 + 0.15 + 0.10 + 0.05 = 1.00 |
| Aging half-life | 60 seconds |
| Auction states | 9 |
| Terminal states | 5 |
| Tie-break levels | 4 |
| Max tested robots | 5 |

---

## LIKELY INTERVIEWER / JUDGE QUESTIONS

### Architecture

**Q**: "Why not a central auctioneer?"
**A**: SIH requirement: "Real-time robot coordination must NOT require every
movement decision to pass through a central server." Our design uses pure
functions that every participant can invoke independently. Central
coordination is a single point of failure.

**Q**: "Is this truly decentralized?"
**A**: The ranking algorithm is decentralized — any participant with the same
bid set and config computes the same winner. The current implementation is a
single-node prototype, but the architecture supports distributed execution.
The key insight is that `compute_ranking()` is a pure function.

**Q**: "How does this scale to 50 robots?"
**A**: Each auction involves only the 2–5 robots in a specific conflict, not
the entire fleet. With 50 robots, there might be 10 concurrent local auctions,
each with O(5 log 5) complexity. Total work is O(50 log 5), not O(50 log 50).

### Algorithm

**Q**: "How do you prevent starvation?"
**A**: The aging component uses bounded exponential saturation:
`1 - exp(-t × ln2 / half_life)`. A robot waiting 2× the half-life (120s)
gets aging ≈ 0.75, contributing 0.75 × 0.15 = 0.11 to utility. This is
enough to overcome moderate priority gaps. We have a test
(test_repeated_contention_fairer_ordering) proving a lower-priority robot
with long wait beats a fresh higher-priority robot.

**Q**: "Why weighted sum instead of priority-first?"
**A**: Priority-first (lexicographic) causes permanent starvation: a robot
with priority 0.49 always loses to one with 0.50, regardless of wait time.
Weighted sum allows smooth trade-offs. The aging mechanism ensures dynamic
fairness.

**Q**: "Are these weights optimal?"
**A**: We don't claim optimality. The defaults are documented starting points
based on warehouse coordination heuristics. UtilityConfig is injectable and
testable — weights can be tuned per deployment through configuration, not
code changes.

### Safety

**Q**: "Can two robots both get PROCEED?"
**A**: Not from the same auction. compute_ranking assigns PROCEED only to
rank 1. However, if two robots are in different auctions for different
resources, they can both PROCEED (correctly — they're not in conflict with
each other).

**Q**: "What prevents collisions?"
**A**: The spatio-temporal reservation system. The auction winner gets a
ReservationManager-confirmed reservation for the contested resource during
the conflict time window. Other robots are told to WAIT or YIELD. Collision
prevention is designed into the reservation layer, not the auction layer.

**Q**: "Is this safety-certified?"
**A**: No. This is a research prototype for SIH. We do not claim formal safety
certification. We claim that the design is structured to prevent known
collision scenarios through deterministic coordination and exclusive
reservations. Formal verification would be a separate effort.

### Implementation

**Q**: "Why is auction.py 1000 lines?"
**A**: It contains 8 classes, 5 functions, 3 enums, and extensive validation.
Breaking it into sub-modules (contracts, utility, engine) would be reasonable
for maintainability but doesn't reduce total complexity. Each entity is small
and focused.

**Q**: "Why Pydantic instead of dataclasses?"
**A**: Consistent with Steps 1–3. Pydantic provides built-in validation
(ge=0, le=1, non-whitespace, finite), JSON serialization, and schema
enforcement. These contracts cross module boundaries and need validation
at construction time.

**Q**: "What happens when the reservation fails?"
**A**: Status becomes RESERVATION_COMMIT_FAILED. The winner's ranking is
preserved (they had the highest utility) but no reservation is granted. The
coordination loop (future phase) would create a new auction with version+1.
Test test_retry_after_failed_commit proves this works.
