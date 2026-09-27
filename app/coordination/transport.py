"""
SWARMOS Coordination — Transport Abstraction

Defines a minimal protocol (structural interface) for message transport.

The coordination engine programs against this interface so that the
underlying transport can be swapped without rewriting coordination logic:

             Coordination Engine
                     │
                     ▼
             TransportInterface
              ╱        │        ╲
             ╱         │         ╲
          HTTP     WebSocket    Future
         (now)      (later)    (Zenoh, ROS 2, …)

No concrete transport is implemented in this module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.coordination.messages import CoordinationMessage


@runtime_checkable
class TransportInterface(Protocol):
    """
    Minimal contract for coordination-message transport.

    Implementations may be async HTTP clients, WebSocket handlers,
    ROS 2 publishers, Zenoh sessions, in-memory test buses, etc.

    Using :class:`typing.Protocol` (structural subtyping) so that
    concrete transports do not need to inherit from this class —
    they only need to implement the method signatures.
    """

    async def send(
        self,
        message: CoordinationMessage,
        target_id: str,
    ) -> None:
        """
        Send a message to a specific recipient.

        Parameters
        ----------
        message :
            Validated coordination message envelope.
        target_id :
            Identifier of the intended recipient robot / service.
        """
        ...

    async def broadcast(
        self,
        message: CoordinationMessage,
    ) -> None:
        """
        Broadcast a message to all reachable peers.

        Parameters
        ----------
        message :
            Validated coordination message envelope.
        """
        ...

    async def receive(self) -> CoordinationMessage:
        """
        Wait for and return the next inbound coordination message.

        Returns
        -------
        CoordinationMessage
            The next validated message received from the transport layer.
        """
        ...
