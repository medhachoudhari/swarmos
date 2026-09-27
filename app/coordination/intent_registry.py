"""
SWARMOS Coordination — Path Intent Registry

Stores the latest ``MovementIntent`` for each robot, keyed by the sending
robot's ID (from ``CoordinationMessage.sender_id``).

Ordering rules
--------------
- ``update_from_message``:  uses ``MovementIntent.path_version`` as the
  primary ordering signal — a higher version replaces a lower one.
  When versions are equal, ``CoordinationMessage.sequence`` is the
  tiebreaker.  If both are equal, the update is rejected.
- ``update``:  direct injection.  Replaces if ``path_version >= stored``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.coordination.models import MovementIntent
from app.coordination.messages import CoordinationMessage, MessageType


# ---------------------------------------------------------------------------
# Internal entry
# ---------------------------------------------------------------------------

@dataclass
class _IntentEntry:
    """MovementIntent + sender identity + message metadata."""

    intent: MovementIntent
    robot_id: str
    sequence: int | None = None
    msg_timestamp: float | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class IntentRegistry:
    """
    Thread-unsafe registry of the latest ``MovementIntent`` per robot.

    Designed to run locally — no central backend dependency.
    """

    def __init__(self) -> None:
        self._intents: dict[str, _IntentEntry] = {}

    # -- message-based update -----------------------------------------------

    def update_from_message(self, msg: CoordinationMessage) -> bool:
        """
        Update intent from a ``PATH_INTENT`` coordination message.

        Returns ``True`` if accepted, ``False`` if stale/duplicate or
        wrong message type.

        Primary ordering: ``MovementIntent.path_version`` (higher wins).
        Tiebreaker for equal versions: ``CoordinationMessage.sequence``
        (higher wins).  If both are equal, the update is rejected.
        """
        if msg.type != MessageType.PATH_INTENT:
            return False

        intent = MovementIntent.model_validate(msg.payload)
        robot_id = msg.sender_id

        existing = self._intents.get(robot_id)
        if existing is not None:
            if intent.path_version < existing.intent.path_version:
                return False
            if intent.path_version == existing.intent.path_version:
                if (existing.sequence is not None
                        and msg.sequence <= existing.sequence):
                    return False

        self._intents[robot_id] = _IntentEntry(
            intent=intent,
            robot_id=robot_id,
            sequence=msg.sequence,
            msg_timestamp=msg.timestamp,
        )
        return True

    # -- direct update -------------------------------------------------------

    def update(self, robot_id: str, intent: MovementIntent) -> None:
        """
        Directly inject a ``MovementIntent``.

        Replaces if ``intent.path_version >= stored version``.
        Always replaces if no prior entry exists.
        """
        existing = self._intents.get(robot_id)
        if existing is not None:
            if intent.path_version < existing.intent.path_version:
                return

        self._intents[robot_id] = _IntentEntry(
            intent=intent,
            robot_id=robot_id,
        )

    # -- queries -------------------------------------------------------------

    def get(self, robot_id: str) -> MovementIntent | None:
        """Return the latest intent for *robot_id*, or ``None``."""
        entry = self._intents.get(robot_id)
        return entry.intent if entry is not None else None

    def get_all(self) -> dict[str, MovementIntent]:
        """Return a snapshot of all current intents."""
        return {rid: e.intent for rid, e in self._intents.items()}

    def remove(self, robot_id: str) -> bool:
        """Remove an intent.  Returns ``True`` if it existed."""
        return self._intents.pop(robot_id, None) is not None

    def clear(self) -> None:
        """Remove all intents."""
        self._intents.clear()
