# SWARMOS — Integration Contracts (v1)

**Status:** v1 proposal. Sections marked `NEEDS CONFIRMATION` require a group
decision. Sections marked `IMPLEMENTED` already exist in code and should not
be changed without tests and a migration note.

**Owner of this document:** M2 (Backend / Integration Owner).

Every member codes against this document. If you need to change a contract,
change it here first and tell the affected member.

---

## 0. Global conventions (decide these ONCE, first meeting)

| Item | Proposed value | Status |
|---|---|---|
| Coordinate system | Continuous metres, float, origin bottom-left, +x right, +y up | NEEDS CONFIRMATION |
| Grid vs continuous | Planner works on integer grid cells; coordination works in continuous metres; M5 owns the conversion | NEEDS CONFIRMATION |
| Cell size | 1.0 m per grid cell | NEEDS CONFIRMATION |
| Time | Float seconds. Simulation time, NOT wall clock. Always passed explicitly | IMPLEMENTED |
| Robot ID format | `amr-01` .. `amr-50` (lowercase, zero-padded 2 digits) | NEEDS CONFIRMATION |
| Task ID format | `task-0001` | NEEDS CONFIRMATION |
| Heading | Radians, strictly `[0, 2*pi)` | IMPLEMENTED |
| Battery | Percent, float `0..100` | IMPLEMENTED |
| Velocity | Metres/second, `>= 0`, finite | IMPLEMENTED |
| JSON casing | `snake_case` everywhere, including the frontend | NEEDS CONFIRMATION |
| No NaN / Inf | Rejected by validators at every boundary | IMPLEMENTED |

**Why this matters:** the single most common integration failure is one
member emitting metres while another expects grid cells. Fix it here, once.

---

## 1. Already-implemented contracts (M4 — do not break)

These exist in `app/coordination/` and are covered by 296 passing tests.

### 1.1 `Position`
```python
{"x": float, "y": float}    # metres, finite, NaN/Inf rejected
```

### 1.2 `RobotStatus` (enum)
```
AVAILABLE | MOVING | WAITING | BLOCKED | FAILED | CHARGING
```

### 1.3 `MovementIntent`
```python
{
  "target":       {"x": float, "y": float},
  "path":         [{"x": float, "y": float}, ...],   # may be empty
  "eta":          float | None,                      # seconds, >= 0
  "intent_id":    str,                               # non-empty, non-whitespace
  "path_version": int                                # >= 1, increments on replan
}
```
**`path_version` is critical.** Every replan MUST increment it. Coordination
uses it to reject stale bids and stale intents.

### 1.4 `AMRState`
```python
{
  "robot_id":        str,
  "timestamp":       float,        # simulation seconds, finite
  "position":        Position,
  "velocity":        float,        # m/s, >= 0
  "heading":         float,        # radians, [0, 2*pi)
  "status":          RobotStatus,
  "battery":         float,        # 0..100
  "current_task_id": str | None,
  "movement_intent": MovementIntent | None
}
```

### 1.5 `CoordinationMessage` (the envelope for all peer traffic)
```python
{
  "schema_version": "1.0",
  "message_id":     str,           # unique per message instance
  "type":           MessageType,
  "sender_id":      str,
  "timestamp":      float,
  "sequence":       int,           # >= 0, monotonic PER SENDER
  "target_id":      str | None,    # None = broadcast
  "payload":        dict           # type-specific
}
```
`MessageType` today: `ROBOT_STATE`, `PATH_INTENT`.
Step 4B adds: `AUCTION_ANNOUNCE`, `AUCTION_BID`, `AUCTION_DECISION`,
`AUCTION_ABORT`. Later: `HEARTBEAT`, `CONFLICT_ALERT`, `RESERVATION_*`.

**Rule:** `sequence` must be monotonically increasing per sender. Dedup and
out-of-order rejection depend on it.

### 1.6 `ConflictResult` (M4 output, consumed by M1 and M6)
```python
{
  "robot_a_id": str, "robot_b_id": str,
  "conflict_type": "VERTEX" | "EDGE_SWAP" | "PROXIMITY",
  "location": Position,
  "time_window_start": float, "time_window_end": float,
  "min_distance": float,
  "robot_a_path_version": int, "robot_b_path_version": int
}
```

### 1.7 `AuctionDecision` (M4 output — the Decision Inspector data source)
```python
{
  "auction_id": str, "auction_version": int,
  "decision_id": str,          # deterministic, identical on every peer
  "winner_id": str,
  "participant_ids": [str],
  "resource_id": str,
  "time_window_start": float, "time_window_end": float,
  "winning_utility": float,
  "status": AuctionStatus,
  "ranking": [
    {
      "robot_id": str, "rank": int,
      "utility_breakdown": {
        "priority_component": float, "deadline_component": float,
        "battery_component": float,  "aging_component": float,
        "delay_component": float,    "distance_component": float,
        "effective_utility": float
      },
      "outcome": "PROCEED" | "WAIT" | "YIELD" | "SLOW" | "REROUTE"
    }
  ],
  "reservation_result": ReservationResult | None
}
```
`utility_breakdown` is the explainability payload. M1 renders it directly;
these are real computed numbers, not generated prose.

---

## 2. Module interface matrix

| From | To | Data | Mechanism | Status |
|---|---|---|---|---|
| M5 sim | M4 coord | `AMRState` per robot per tick | Python call / `ROBOT_STATE` msg | IMPLEMENTED (consumer side) |
| M5 planner | M4 coord | `MovementIntent` (path + `path_version`) | Python call / `PATH_INTENT` msg | IMPLEMENTED (consumer side) |
| M4 coord | M5 planner | reroute request: `robot_id`, blocked cells, reason | `RerouteRequest` (Step 4B+) | NEEDS CONFIRMATION |
| M4 coord | M5 sim | per-robot action: PROCEED/WAIT/SLOW/YIELD/REROUTE | `CoordinationDirective` | NEEDS CONFIRMATION |
| M4 coord | M2 backend | decisions, conflicts, reservations, incidents | event stream | NEEDS CONFIRMATION |
| M2 backend | M1 frontend | fleet snapshot at ~10 Hz | WebSocket `/ws/fleet` | NEEDS CONFIRMATION |
| M2 backend | M1 frontend | tasks, robots, scenarios, benchmarks | REST `/api/v1/*` | NEEDS CONFIRMATION |
| M3 AI/ML | M4 coord | advisory action + confidence | `MLAdvice` | NEEDS CONFIRMATION |
| M3 AI/ML | M5 planner | congestion field (cost multipliers) | `CongestionField` | NEEDS CONFIRMATION |
| M4/M5 | M6 db | event log for replay + metrics | DB insert / event bus | NEEDS CONFIRMATION |
| M6 db | M1 frontend | KPIs, benchmark comparison, replay frames | REST via M2 | NEEDS CONFIRMATION |
| M6 db | M3 AI/ML | training dataset export | CSV / Parquet | NEEDS CONFIRMATION |

---

## 3. Proposed new contracts

### 3.1 `CoordinationDirective` — M4 to M5 (what a robot should do now)
```python
{
  "robot_id": str,
  "tick": int,
  "action": "PROCEED" | "WAIT" | "SLOW" | "YIELD" | "REROUTE",
  "speed_factor": float,        # 1.0 normal, 0.5 for SLOW, 0.0 for WAIT
  "hold_until": float | None,   # sim seconds
  "reason": str,                # e.g. "lost_auction:auc-1_v1"
  "decision_id": str | None     # links back to AuctionDecision
}
```

### 3.2 `RerouteRequest` — M4 to M5 planner
```python
{
  "robot_id": str,
  "from": Position,
  "to": Position,
  "blocked_cells": [[int, int]],       # hard exclusions
  "penalty_cells": [[int, int], float] # soft cost multipliers (congestion)
  "reason": "CONFLICT" | "BLOCKED_AISLE" | "DEADLOCK" | "PEER_FAILURE",
  "requested_at": float
}
```
Planner responds with a `MovementIntent` whose `path_version` is
**strictly greater** than the robot's current one.

### 3.3 `MLAdvice` — M3 to M4 (advisory only)
```python
{
  "robot_id": str,
  "tick": int,
  "recommended_action": "MOVE" | "WAIT" | "REROUTE" | "CHARGE",
  "confidence": float,          # 0..1
  "model_version": str,
  "features_used": {str: float} # for the Decision Inspector
}
```

**SAFETY RULE — non-negotiable, and this is a judge-facing claim:**
The ML model is **advisory**. It may influence utility weighting or trigger a
reroute evaluation. It may **never** override a reservation check or permit
entry into an unreserved contested corridor. Safety is enforced by the
deterministic reservation engine, not by a learned model.

State this explicitly in the presentation. It converts "is your AI safe?"
from a weakness into a strength.

### 3.4 `CongestionField` — M3 to M5 planner
```python
{
  "tick": int,
  "cell_size": float,
  "width": int, "height": int,
  "cost_multiplier": [[float]],  # >= 1.0 per cell, row-major
  "horizon": float,              # seconds this prediction covers
  "model_version": str
}
```

### 3.5 Fleet snapshot — M2 to M1 over WebSocket
```python
{
  "tick": int,
  "sim_time": float,
  "robots": [AMRState],
  "active_conflicts": [ConflictResult],
  "active_reservations": [{"resource_id": str, "robot_id": str,
                            "start_time": float, "end_time": float}],
  "recent_decisions": [AuctionDecision],
  "incidents": [{"type": str, "robot_ids": [str], "at": float, "detail": str}],
  "kpis": {"tasks_completed": int, "collisions": int, "deadlocks": int,
            "avg_wait": float, "throughput": float}
}
```
Performance note for M1: at 50 robots and 10 Hz this is a large payload.
Keep it out of React state — render the map from a mutable ref into
canvas/WebGL, and only put low-frequency aggregates into React state.

### 3.6 Event log — everyone to M6
```python
{
  "event_id": str, "tick": int, "sim_time": float,
  "run_id": str,                # groups one simulation run
  "event_type": str,            # ROBOT_MOVED, CONFLICT_DETECTED,
                                # AUCTION_CREATED, AUCTION_DECIDED,
                                # RESERVATION_GRANTED, RESERVATION_DENIED,
                                # DEADLOCK_DETECTED, ROBOT_FAILED,
                                # TASK_COMPLETED, REROUTE_TRIGGERED, ...
  "robot_ids": [str],
  "payload": dict
}
```
`run_id` + `tick` ordering is what makes replay and benchmark comparison
possible. Every member emitting events must include both.

---

## 4. Benchmark contract (this produces the headline SIH number)

Owner: M6, with M5 providing the baseline policy.

Two policies run over **identical seeds, maps, and task streams**:

| Policy | Behaviour |
|---|---|
| `STOP_AND_WAIT` (baseline) | Robot detects an occupied/contested cell ahead and halts until clear. No negotiation, no reservation, no reroute. |
| `SWARMOS` | Full coordination: conflict prediction, auction, spatio-temporal reservation, reroute. |

Required output per run:
```python
{
  "run_id": str, "policy": "STOP_AND_WAIT" | "SWARMOS",
  "seed": int, "robot_count": int, "task_count": int, "map_id": str,
  "total_completion_time": float,   # PRIMARY SIH METRIC
  "collisions": int,                # MUST be 0 for SWARMOS
  "deadlocks": int,
  "tasks_completed": int,
  "avg_waiting_time": float,
  "reroute_count": int,
  "total_distance": float,
  "congestion_index": float,
  "failure_recovery_time": float | None,
  "comms_degradation_pct": float
}
```

**Hard rule (handoff section 19):** the improvement percentage is computed
from these numbers at runtime. It is never hard-coded, never estimated, never
rounded up for the slide. A real 14% is worth more than a fabricated 22%,
because a fabricated number will not survive the Q&A.

---

## 5. Highest-risk contract gaps (top of the first meeting agenda)

1. **Grid vs continuous coordinates.** M5's planner is integer grid; M4's
   conflict detection is continuous metres. Who converts, and where? This is
   the #1 integration risk.
2. **`path_version` discipline.** If the planner ever returns a new path
   without incrementing `path_version`, coordination will accept stale bids
   and the safety argument collapses. Must be enforced in the planner.
3. **Who is authoritative for robot state?** Proposal: M5's simulator is the
   single source of truth for physical state; everyone else holds a read
   replica. Must be agreed explicitly.
4. **Tick rate and who drives the loop.** Proposal: M5 drives the simulation
   tick; M2 drives the API/WebSocket loop; they are decoupled by a queue.
5. **Does the ML model sit in the decision path or beside it?** Answer must be
   *beside it* (advisory), for both safety and defensibility.
6. **Where does the reservation authority live?** Currently one shared
   `ReservationManager` instance. This is a hidden centralised component and
   must be described honestly, or replaced with per-robot replicas reconciled
   by the deterministic `decision_id`.

---

## 6. Change process

1. Propose the change in this file via a pull request.
2. Tag the affected members.
3. If it breaks an implemented contract, include a migration note and update
   the tests in the same PR.
4. Never change a contract silently. The 296-test suite must stay green.
