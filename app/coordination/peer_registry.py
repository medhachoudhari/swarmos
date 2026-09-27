"""
SWARMOS Coordination — Peer State Registry & Neighbor Awareness

Maintains the latest known state of peer AMR robots.  Supports both
message-based updates (with sequence-based ordering) and direct updates
(for simulator / internal use).

Ordering rules
--------------
- ``update_from_message``:  uses ``CoordinationMessage.sequence`` as the
  primary ordering signal — a higher sequence replaces a lower one.
  Equal or lower sequences are rejected.
- ``update``:  direct ``AMRState`` injection (e.g. from the local
  simulator).  Always overwrites — no sequence ordering guarantee.

Neighbor awareness is derived from stored peer positions using Euclidean
distance filtering — no network discovery or external spatial indexing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.coordination.models import AMRState
from app.coordination.messages import CoordinationMessage, MessageType


# ---------------------------------------------------------------------------
# Internal entry
# ---------------------------------------------------------------------------

@dataclass
class _PeerEntry:
    """AMRState + message-level ordering metadata."""

    state: AMRState
    sequence: int | None = None
    msg_timestamp: float | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PeerStateRegistry:
    """
    Thread-unsafe registry of the latest known AMR state per robot.

    Designed to run locally on each AMR / edge coordinator — no central
    backend dependency required.
    """

    def __init__(self) -> None:
        self._peers: dict[str, _PeerEntry] = {}

    # -- message-based update -----------------------------------------------

    def update_from_message(self, msg: CoordinationMessage) -> bool:
        """
        Update peer state from a ``ROBOT_STATE`` coordination message.

        Returns ``True`` if the state was accepted (newer or first-seen).
        Returns ``False`` if rejected (stale / duplicate / wrong type).

        Ordering: ``CoordinationMessage.sequence`` is the primary signal.
        A message whose sequence is **not strictly greater** than the
        stored sequence is rejected.
        """
        if msg.type != MessageType.ROBOT_STATE:
            return False

        robot_id = msg.sender_id
        existing = self._peers.get(robot_id)

        if existing is not None and existing.sequence is not None:
            if msg.sequence <= existing.sequence:
                return False

        state = AMRState.model_validate(msg.payload)
        self._peers[robot_id] = _PeerEntry(
            state=state,
            sequence=msg.sequence,
            msg_timestamp=msg.timestamp,
        )
        return True

    # -- direct update (simulator / internal) --------------------------------

    def update(self, state: AMRState) -> None:
        """
        Directly inject an ``AMRState`` (e.g. from the local simulator).

        Always overwrites.  No sequence-based ordering — the caller is
        responsible for providing the latest state.
        """
        self._peers[state.robot_id] = _PeerEntry(state=state)

    # -- queries -------------------------------------------------------------

    def get(self, robot_id: str) -> AMRState | None:
        """Return the latest state for *robot_id*, or ``None``."""
        entry = self._peers.get(robot_id)
        return entry.state if entry is not None else None

    def get_all(self) -> dict[str, AMRState]:
        """Return a snapshot of all known peer states."""
        return {rid: e.state for rid, e in self._peers.items()}

    def remove(self, robot_id: str) -> bool:
        """Remove a peer.  Returns ``True`` if it existed."""
        return self._peers.pop(robot_id, None) is not None

    def is_stale(
        self,
        robot_id: str,
        current_time: float,
        max_age: float,
    ) -> bool:
        """
        Check whether a peer's state is older than *max_age* seconds.

        Uses ``AMRState.timestamp`` compared to the caller-supplied
        *current_time* — no hidden wall-clock dependency.

        Returns ``True`` if stale **or** unknown.
        """
        entry = self._peers.get(robot_id)
        if entry is None:
            return True
        return (current_time - entry.state.timestamp) > max_age

    def get_neighbors(self, robot_id: str, radius: float) -> list[AMRState]:
        """
        Return peers within *radius* metres of *robot_id*.

        Excludes *robot_id* itself.  Results are sorted by ascending
        Euclidean distance, then by ``robot_id`` for deterministic ordering.
        """
        origin_entry = self._peers.get(robot_id)
        if origin_entry is None:
            return []

        ox = origin_entry.state.position.x
        oy = origin_entry.state.position.y
        neighbors: list[tuple[float, AMRState]] = []

        for rid, entry in self._peers.items():
            if rid == robot_id:
                continue
            dx = entry.state.position.x - ox
            dy = entry.state.position.y - oy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist <= radius:
                neighbors.append((dist, entry.state))

        neighbors.sort(key=lambda t: (t[0], t[1].robot_id))
        return [s for _, s in neighbors]

    def clear(self) -> None:
        """Remove all peers."""
        self._peers.clear()
