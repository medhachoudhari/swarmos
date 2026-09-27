"""X-10 / N9: message integrity and adversarial robot containment.

The threat model, stated plainly
--------------------------------
A robot on the fleet radio is misbehaving. Either its software has faulted or
it has been compromised. It broadcasts coordination messages that are
syntactically perfect and semantically hostile: claiming space it is not in,
claiming to be a robot it is not, or flooding the channel so honest peers cannot
be heard. This is the case a warehouse fleet actually has to survive, and it is
the reason a defence contractor cares about the coordination layer at all.

Two mechanisms, and the distinction between them matters
-------------------------------------------------------
1. AUTHENTICATION (this file, `MessageAuthenticator`). An HMAC over the
   envelope's canonical bytes, keyed per robot. This answers "did R007 really
   send this?" and nothing else. It stops IMPERSONATION.

2. BEHAVIOURAL CONTAINMENT (this file, `SentinelCouncil`). Signatures cannot
   help against a robot that is genuinely itself and genuinely lying - the
   message is authentic, the content is false. That is caught by watching what a
   peer CLAIMS against what the fleet OBSERVES, and by requiring a quorum of
   independent witnesses before anyone is excluded.

Why a quorum and not a single accuser
-------------------------------------
If one robot could quarantine another on its own say-so, then compromising one
robot would let an attacker silence the entire fleet one peer at a time - the
containment mechanism becomes the attack. So an accusation from a single
witness is recorded and does nothing. Only when QUORUM independent witnesses
independently accuse the same peer does the radio actually cut it off. This is
the same reasoning behind requiring multiple confirmations in a failure
detector, applied to malice rather than silence.

Why HMAC and not public-key signatures
--------------------------------------
Stated honestly because it is a fair question: a real deployment would use
per-robot asymmetric keys so that no peer holds another's signing key. HMAC
with a shared fleet key demonstrates the mechanism and the containment policy
at a fraction of the compute, which matters inside a 100 ms tick budget. The
architecture does not change if the primitive is swapped; `MessageAuthenticator`
is the only place that would need to be replaced. This is a deliberate
simplification, not an oversight, and it is recorded as such.

Determinism (N3) is preserved: HMAC-SHA256 is deterministic, the canonical
byte encoding sorts its keys, and the council iterates witnesses in sorted
order. Nothing here reads a clock or an RNG.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# Number of INDEPENDENT witnesses required before a peer is contained. Two is
# the smallest number that is not "one robot's word", which is the property that
# actually matters; a larger quorum buys little on a 24-50 robot floor and costs
# detection latency.
QUORUM = 2

# How far a claimed position may differ from the observed position before it is
# treated as a false claim, in metres. 1.5 m is a little over two robot
# footprints: comfortably outside sensing noise, comfortably inside "this robot
# is lying about where it is".
CLAIM_TOLERANCE_M = 1.5

# Messages per robot per tick above which the sender is treated as flooding the
# channel. At 10 Hz an honest robot sends a heartbeat plus a small number of
# coordination messages; 12 in a single tick is not a busy robot, it is a
# denial-of-service.
FLOOD_PER_TICK = 12

# Consecutive ticks a quarantined robot must behave before release is offered.
# Containment that can never be lifted is a fault, not a safety mechanism: a
# robot that faulted transiently and recovered should be able to rejoin.
REHABILITATION_TICKS = 50


class IntegrityVerdict(str):
    """Why a message was accepted or rejected. A plain string subclass so it
    serialises to JSON with no special handling."""

    OK = "ok"
    BAD_SIGNATURE = "bad_signature"
    UNKNOWN_SENDER = "unknown_sender"
    UNSIGNED = "unsigned"


def canonical_bytes(
    *,
    message_id: str,
    sender_id: str,
    msg_type: str,
    sequence: int,
    target_id: Optional[str],
    payload: dict,
) -> bytes:
    """Deterministic byte encoding of the fields a signature must cover.

    Keys are sorted and separators fixed so the same logical message always
    produces the same bytes. The timestamp is deliberately EXCLUDED: it is
    sender-side wall clock, it is not part of the message's meaning, and
    including it would make a signature unverifiable after any clock
    normalisation in transit.
    """
    return json.dumps(
        {
            "message_id": message_id,
            "sender_id": sender_id,
            "type": str(msg_type),
            "sequence": int(sequence),
            "target_id": target_id,
            "payload": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def sign_bytes(key: bytes, body: bytes) -> str:
    return hmac.new(key, body, hashlib.sha256).hexdigest()


@dataclass
class AuthStats:
    signed: int = 0
    verified: int = 0
    rejected: int = 0
    reasons: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "signed": self.signed,
            "verified": self.verified,
            "rejected": self.rejected,
            "reasons": dict(sorted(self.reasons.items())),
        }


class MessageAuthenticator:
    """Signs and verifies coordination messages with a per-robot HMAC key.

    Signatures are held SIDE-BAND, keyed by message_id, rather than added as a
    field on CoordinationMessage. The envelope is a frozen contract with one
    canonical model per concept; bolting a transport-security field onto it
    would break that and force every existing producer to change. A real
    deployment would carry the signature in a transport header, which is
    structurally the same thing.
    """

    def __init__(self, *, fleet_key: bytes = b"swarmos-demo-fleet-key") -> None:
        self._fleet_key = fleet_key
        self._known: set[str] = set()
        self._signatures: dict[str, str] = {}
        self.stats = AuthStats()

    def key_for(self, robot_id: str) -> bytes:
        """Derive a per-robot key from the fleet key.

        Derivation rather than one shared secret so that a signature is bound to
        a specific sender: a robot holding the fleet key still cannot produce a
        valid signature for a peer's id without deriving that peer's key, and
        the derivation is what a real system would replace with a private key.
        """
        return hmac.new(self._fleet_key, robot_id.encode("utf-8"), hashlib.sha256).digest()

    def enrol(self, robot_ids: Iterable[str]) -> None:
        """Register robots as legitimate fleet members."""
        for rid in robot_ids:
            self._known.add(rid)

    def revoke(self, robot_id: str) -> None:
        self._known.discard(robot_id)

    def sign(self, msg) -> str:
        body = canonical_bytes(
            message_id=msg.message_id,
            sender_id=msg.sender_id,
            msg_type=getattr(msg.type, "value", msg.type),
            sequence=msg.sequence,
            target_id=msg.target_id,
            payload=msg.payload,
        )
        sig = sign_bytes(self.key_for(msg.sender_id), body)
        self._signatures[msg.message_id] = sig
        self.stats.signed += 1
        return sig

    def verify(self, msg, signature: Optional[str] = None) -> str:
        """Return an IntegrityVerdict for this message.

        A message whose signature is absent is UNSIGNED, which is reported
        separately from BAD_SIGNATURE. Collapsing the two would hide the
        difference between a robot that never signed and one that signed wrongly,
        and those are different faults.
        """
        if signature is None:
            signature = self._signatures.get(msg.message_id)

        if msg.sender_id not in self._known:
            return self._reject(IntegrityVerdict.UNKNOWN_SENDER)
        if signature is None:
            return self._reject(IntegrityVerdict.UNSIGNED)

        body = canonical_bytes(
            message_id=msg.message_id,
            sender_id=msg.sender_id,
            msg_type=getattr(msg.type, "value", msg.type),
            sequence=msg.sequence,
            target_id=msg.target_id,
            payload=msg.payload,
        )
        expected = sign_bytes(self.key_for(msg.sender_id), body)
        # compare_digest, not ==, so verification time does not depend on how
        # many leading bytes matched.
        if not hmac.compare_digest(expected, signature):
            return self._reject(IntegrityVerdict.BAD_SIGNATURE)

        self.stats.verified += 1
        return IntegrityVerdict.OK

    def _reject(self, reason: str) -> str:
        self.stats.rejected += 1
        self.stats.reasons[reason] = self.stats.reasons.get(reason, 0) + 1
        return reason


@dataclass
class Accusation:
    """One witness's claim that one peer misbehaved."""

    accuser: str
    accused: str
    reason: str
    tick: int
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "accuser": self.accuser,
            "accused": self.accused,
            "reason": self.reason,
            "tick": self.tick,
            "detail": self.detail,
        }


@dataclass
class ContainmentEvent:
    """A quorum was reached and a peer was contained, or was released."""

    robot_id: str
    tick: int
    action: str  # "quarantine" or "release"
    reason: str
    witnesses: tuple
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "robot_id": self.robot_id,
            "tick": self.tick,
            "action": self.action,
            "reason": self.reason,
            "witnesses": list(self.witnesses),
            "detail": self.detail,
        }


class SentinelCouncil:
    """Quorum-based adversarial containment (N9).

    The council holds accusations, and only acts when QUORUM distinct witnesses
    independently accuse the same peer. It does not itself cut anyone off: it
    returns events and the caller applies them to the radio. Keeping the
    decision and the enforcement separate means the decision is testable without
    a radio, and the radio remains the single place where connectivity is
    enforced.
    """

    REASON_FALSE_CLAIM = "false_position_claim"
    REASON_BAD_SIGNATURE = "bad_signature"
    REASON_FLOOD = "channel_flood"
    REASON_IMPERSONATION = "impersonation"

    def __init__(self, *, quorum: int = QUORUM,
                 tolerance_m: float = CLAIM_TOLERANCE_M,
                 flood_per_tick: int = FLOOD_PER_TICK,
                 rehabilitation_ticks: int = REHABILITATION_TICKS) -> None:
        self.quorum = quorum
        self.tolerance_m = tolerance_m
        self.flood_per_tick = flood_per_tick
        self.rehabilitation_ticks = rehabilitation_ticks

        # accused -> reason -> set of accusers
        self._accusations: dict[str, dict[str, set]] = defaultdict(
            lambda: defaultdict(set)
        )
        self._contained: dict[str, ContainmentEvent] = {}
        self._clean_ticks: dict[str, int] = defaultdict(int)
        self.log: list[ContainmentEvent] = []
        self.accusation_log: list[Accusation] = []
        # A witness that accuses everyone is itself the anomaly. Counted so the
        # behaviour is visible rather than trusted.
        self.accusations_by: dict[str, int] = defaultdict(int)

    # ----------------------------------------------------------- accusations

    def accuse(self, accuser: str, accused: str, reason: str, tick: int,
               detail: str = "") -> Optional[ContainmentEvent]:
        """Record an accusation. Returns a containment event iff quorum is met.

        Self-accusation is discarded. A compromised robot must not be able to
        manufacture a quorum by accusing a peer repeatedly under different
        reasons, so witnesses are held as a SET per reason and a second
        accusation from the same witness adds nothing.
        """
        if accuser == accused:
            return None

        self.accusation_log.append(Accusation(accuser, accused, reason, tick, detail))
        self.accusations_by[accuser] += 1
        witnesses = self._accusations[accused][reason]
        witnesses.add(accuser)

        if accused in self._contained:
            return None
        if len(witnesses) < self.quorum:
            # Deliberately does nothing. One robot's word is not enough, because
            # if it were, compromising one robot would let an attacker silence
            # the fleet one peer at a time.
            return None

        event = ContainmentEvent(
            robot_id=accused,
            tick=tick,
            action="quarantine",
            reason=reason,
            witnesses=tuple(sorted(witnesses)),
            detail=detail,
        )
        self._contained[accused] = event
        self._clean_ticks[accused] = 0
        self.log.append(event)
        return event

    # -------------------------------------------------------------- watching

    def audit_claim(self, *, accuser: str, accused: str,
                    claimed: tuple[float, float],
                    observed: Optional[tuple[float, float]],
                    tick: int) -> Optional[ContainmentEvent]:
        """One witness compares a peer's CLAIMED position against what it sees.

        `observed` of None means the witness cannot see the peer at all, which
        is NOT evidence of lying - the peer may simply be out of sensor range or
        occluded. Treating absence of observation as proof of malice would make
        every occlusion an accusation.
        """
        if observed is None:
            return None
        dx = claimed[0] - observed[0]
        dy = claimed[1] - observed[1]
        error = (dx * dx + dy * dy) ** 0.5
        if error <= self.tolerance_m:
            return None
        return self.accuse(
            accuser,
            accused,
            self.REASON_FALSE_CLAIM,
            tick,
            detail=(
                f"claimed ({claimed[0]:.2f}, {claimed[1]:.2f}) but was observed "
                f"at ({observed[0]:.2f}, {observed[1]:.2f}), an error of "
                f"{error:.2f} m against a {self.tolerance_m:.2f} m tolerance"
            ),
        )

    def audit_traffic(self, *, accuser: str, counts: dict, tick: int) -> list:
        """Flag peers that sent more messages this tick than an honest robot can."""
        events = []
        for rid in sorted(counts):
            if counts[rid] > self.flood_per_tick:
                ev = self.accuse(
                    accuser,
                    rid,
                    self.REASON_FLOOD,
                    tick,
                    detail=(
                        f"sent {counts[rid]} messages in one tick, above the "
                        f"{self.flood_per_tick} an honest robot needs"
                    ),
                )
                if ev is not None:
                    events.append(ev)
        return events

    def audit_signature(self, *, accuser: str, accused: str, verdict: str,
                        tick: int) -> Optional[ContainmentEvent]:
        """Turn a failed signature check into an accusation.

        An unknown sender is treated as impersonation rather than a bad
        signature: a robot id that was never enrolled is not a fleet member
        having a bad day, it is something pretending to be one.
        """
        if verdict == IntegrityVerdict.OK:
            return None
        if verdict == IntegrityVerdict.UNKNOWN_SENDER:
            return self.accuse(
                accuser, accused, self.REASON_IMPERSONATION, tick,
                detail="sender id is not an enrolled fleet member",
            )
        if verdict == IntegrityVerdict.BAD_SIGNATURE:
            return self.accuse(
                accuser, accused, self.REASON_BAD_SIGNATURE, tick,
                detail="message signature did not verify against the sender key",
            )
        return None

    # ---------------------------------------------------------- rehabilitation

    def tick_clean(self, robot_ids: Iterable[str], tick: int) -> list:
        """Credit contained robots for a tick of good behaviour, and release
        any that have earned it.

        Containment that can never be lifted is a fault rather than a safety
        mechanism. A robot that faulted transiently and recovered must be able
        to rejoin, otherwise a single glitch permanently removes fleet capacity.
        """
        released = []
        for rid in sorted(set(robot_ids)):
            if rid not in self._contained:
                continue
            self._clean_ticks[rid] += 1
            if self._clean_ticks[rid] >= self.rehabilitation_ticks:
                event = ContainmentEvent(
                    robot_id=rid,
                    tick=tick,
                    action="release",
                    reason="rehabilitated",
                    witnesses=(),
                    detail=(
                        f"behaved correctly for {self._clean_ticks[rid]} "
                        "consecutive ticks"
                    ),
                )
                del self._contained[rid]
                self._accusations.pop(rid, None)
                self._clean_ticks.pop(rid, None)
                self.log.append(event)
                released.append(event)
        return released

    def reset_clean_streak(self, robot_id: str) -> None:
        """Any fresh misbehaviour restarts the rehabilitation clock."""
        if robot_id in self._contained:
            self._clean_ticks[robot_id] = 0

    # -------------------------------------------------------------- reporting

    def is_contained(self, robot_id: str) -> bool:
        return robot_id in self._contained

    @property
    def contained(self) -> tuple:
        return tuple(sorted(self._contained))

    def pending(self) -> dict:
        """Accusations that have NOT reached quorum, so an operator can see what
        the fleet suspects before anything is acted on."""
        out = {}
        for accused in sorted(self._accusations):
            for reason, witnesses in sorted(self._accusations[accused].items()):
                if accused in self._contained:
                    continue
                if 0 < len(witnesses) < self.quorum:
                    out[f"{accused}:{reason}"] = sorted(witnesses)
        return out

    def stats(self) -> dict:
        return {
            "quorum": self.quorum,
            "contained": list(self.contained),
            "contained_count": len(self._contained),
            "accusations": len(self.accusation_log),
            "pending": self.pending(),
            "events": [e.as_dict() for e in self.log[-10:]],
            "top_accusers": dict(
                sorted(self.accusations_by.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ),
        }

    def clear(self) -> None:
        self._accusations.clear()
        self._contained.clear()
        self._clean_ticks.clear()
        self.log.clear()
        self.accusation_log.clear()
        self.accusations_by.clear()
