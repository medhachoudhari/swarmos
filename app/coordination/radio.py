"""SWARMOS M4 - the bounded radio, link impairment and failure detector.

This module is the honest communication layer. Everything above it - the
arbiter, the reservation manager, the auctions - can only see what this layer
lets through, which is the whole point: a coordination result that depends on
perfect global knowledge is not a result a warehouse can use.

Three claims live here, and each is implemented so that it could fail.

X-25 BOUNDED RADIO. A robot may exchange messages only with peers inside
R_COMM_M = 15 m. The bound is enforced HERE rather than trusted to callers,
because "we only talk to nearby robots" is exactly the sort of statement that
quietly stops being true once someone needs a global lookup to fix a bug. The
consequence is measurable: messages per robot per tick stays flat as the fleet
grows, which is the X-03 evidence that message complexity is O(k) and not
O(N^2). A rising series would be visible in the same counters.

X-02 LINK IMPAIRMENT. Real radio drops packets, delays them and reorders them.
`LinkModel` injects loss, latency and duplication from the simulation's own RNG
stream, so an impaired run is still deterministic and still replayable. Loss is
applied per (sender, receiver) ordered pair so an asymmetric link - A hears B
but B does not hear A - is representable, because that is the case that breaks
naive mutual-agreement protocols.

X-23 FAILURE DETECTION. A robot is SUSPECTED after HEARTBEAT_TIMEOUT_S = 0.2 s
of silence and CONFIRMED_FAILED after CONFIRM_TIMEOUT_S. The two-stage ladder
is deliberate: a single missed heartbeat is a dropped packet, not a death, and a
detector that cannot tell those apart will evict healthy robots the moment the
radio degrades. Only a CONFIRMED failure triggers reservation garbage
collection, because releasing a live robot's reserved corridor is a safety
event, not a housekeeping one.

Time is always passed in by the caller. There is no wall-clock read anywhere in
this module, so a replay at a different speed produces identical decisions.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass

from typing import Iterable, Optional

from app.coordination.messages import CoordinationMessage

# The single definition of radio range in the project. app.sim.policy imports
# its own R_COMM_M for the arbiter's geometry; both must stay equal, and the
# test suite asserts that they are rather than trusting a comment.
R_COMM_M = 15.0

# Heartbeats are emitted at the tick rate, 10 Hz. Two consecutive misses is
# 0.2 s, which is the suspicion threshold: one miss is normal packet loss.
HEARTBEAT_HZ = 10.0
HEARTBEAT_PERIOD_S = 1.0 / HEARTBEAT_HZ
HEARTBEAT_TIMEOUT_S = 0.2

# A further 0.3 s of silence upgrades suspicion to confirmation. Chosen so the
# demo's failure injection resolves visibly within half a second while still
# being several packet-loss events wide.
CONFIRM_TIMEOUT_S = 0.5


class PeerHealth(str, enum.Enum):
    """What the failure detector currently believes about a peer.

    ALIVE      heard from within HEARTBEAT_TIMEOUT_S
    SUSPECTED  silent past the timeout, but not yet long enough to act on
    FAILED     silent past CONFIRM_TIMEOUT_S; safe to garbage-collect
    UNKNOWN    never heard from at all, which is not the same as dead
    """

    ALIVE = "ALIVE"
    SUSPECTED = "SUSPECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LinkProfile:
    """Radio quality. Frozen so it can live inside a frozen scenario spec.

    loss_pct        probability in [0, 100] that a given delivery is dropped
    latency_ticks   whole-tick delivery delay, applied after the loss draw
    duplicate_pct   probability the message is delivered twice
    asymmetric      when True, the loss draw is made per ordered pair, so A
                    may hear B while B does not hear A
    """

    loss_pct: float = 0.0
    latency_ticks: int = 0
    duplicate_pct: float = 0.0
    asymmetric: bool = False

    @property
    def is_perfect(self) -> bool:
        return (
            self.loss_pct <= 0.0
            and self.latency_ticks <= 0
            and self.duplicate_pct <= 0.0
        )

    def as_dict(self) -> dict:
        return {
            "loss_pct": self.loss_pct,
            "latency_ticks": self.latency_ticks,
            "duplicate_pct": self.duplicate_pct,
            "asymmetric": self.asymmetric,
            "perfect": self.is_perfect,
        }


LINK_PERFECT = LinkProfile()
# The demo's degraded-radio setting: one packet in five lost, one tick of delay.
# Severe enough to break a protocol that assumes delivery, mild enough that a
# correctly designed one still coordinates.
LINK_DEGRADED = LinkProfile(loss_pct=20.0, latency_ticks=1, duplicate_pct=2.0)
LINK_SEVERE = LinkProfile(
    loss_pct=45.0, latency_ticks=2, duplicate_pct=5.0, asymmetric=True
)


def euclidean(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


@dataclass
class RadioStats:
    """Counters that make the X-03 and X-02 claims checkable.

    `offered` counts what the coordination layer asked to send; `delivered`
    counts what actually arrived. The gap is the impairment, and reporting both
    is what stops a degraded run from looking like a healthy one.
    """

    ticks: int = 0
    offered: int = 0
    out_of_range: int = 0
    dropped: int = 0
    duplicated: int = 0
    delayed: int = 0
    delivered: int = 0
    quarantined: int = 0

    def as_dict(self, *, robots: int = 0) -> dict:
        denom = max(1, self.ticks) * max(1, robots)
        return {
            "ticks": self.ticks,
            "offered": self.offered,
            "delivered": self.delivered,
            "out_of_range": self.out_of_range,
            "dropped": self.dropped,
            "duplicated": self.duplicated,
            "delayed": self.delayed,
            "quarantined": self.quarantined,
            # The X-03 headline. Flat across fleet sizes means local
            # coordination; rising means the design does not scale.
            "msgs_per_robot_tick": round(self.delivered / denom, 6),
            "delivery_rate": (
                round(self.delivered / self.offered, 4) if self.offered else 1.0
            ),
        }


class BoundedRadio:
    """A range-limited, optionally impaired, deterministic message bus.

    Deterministic because every random draw comes from an injected RNG, in a
    fixed iteration order over sorted peer ids. Two runs of the same seed make
    the same draws in the same order, so an impaired run is as replayable as a
    perfect one - without that property, X-02 and X-22 would contradict each
    other.

    Not thread-safe and not meant to be: one radio belongs to one simulation.
    """

    def __init__(
        self,
        *,
        rng: Optional[random.Random] = None,
        profile: LinkProfile = LINK_PERFECT,
        radius_m: float = R_COMM_M,
    ) -> None:
        self.rng = rng or random.Random(0)
        self.profile = profile
        self.radius_m = float(radius_m)
        self.stats = RadioStats()

        # robot_id -> (x, y), refreshed by the engine each tick. The radio does
        # not own positions; law 1 says the simulation does.
        self._positions: dict[str, tuple[float, float]] = {}
        # Robots whose traffic is discarded on sight (X-10 rogue containment).
        self._quarantined: set[str] = set()
        # Robots whose radio is DEAD rather than distrusted (X-01 blackout).
        # Deliberately a separate set from _quarantined: quarantine is a
        # judgement the fleet makes and can lift, a blackout is a fault the
        # robot is suffering. Collapsing them would let an attack hide behind a
        # broken antenna in the reports.
        self._silenced: set[str] = set()
        # Robots on the far side of a zone partition (X-02 ZONE_PARTITION).
        # A link that crosses the partition boundary does not exist; links on
        # the same side are untouched. Empty means no partition.
        self._partition: frozenset[str] = frozenset()
        # Per-recipient inbox, plus a delay queue keyed by the tick at which a
        # delayed message becomes visible.
        self._inbox: dict[str, list[CoordinationMessage]] = {}
        self._pending: dict[int, list[tuple[str, CoordinationMessage]]] = {}

    # ------------------------------------------------------------------
    # topology
    # ------------------------------------------------------------------
    def set_positions(self, positions: dict[str, tuple[float, float]]) -> None:
        """Refresh the position table the range check reads from."""
        self._positions = dict(positions)

    def set_profile(self, profile: LinkProfile) -> None:
        """Change radio quality mid-run. This is the X-02 injection hook."""
        self.profile = profile

    def set_partition(self, inside: Iterable[str]) -> None:
        """Cut every link between `inside` and everyone else (ZONE_PARTITION).

        Refreshed by the simulation every tick while the fault is active,
        because robots drive in and out of the partitioned zone. An empty
        iterable lifts the partition.
        """
        self._partition = frozenset(inside)

    @property
    def partitioned(self) -> tuple[str, ...]:
        return tuple(sorted(self._partition))

    def _crosses_partition(self, a: str, b: str) -> bool:
        return bool(self._partition) and ((a in self._partition) != (b in self._partition))

    def in_range(self, a: str, b: str) -> bool:
        """Whether two robots can hear each other at all.

        An unknown position means out of range rather than in range. Failing
        closed matters: an optimistic default would silently restore the global
        knowledge this class exists to remove.
        """
        pa, pb = self._positions.get(a), self._positions.get(b)
        if pa is None or pb is None:
            return False
        if self._crosses_partition(a, b):
            return False
        return euclidean(pa[0], pa[1], pb[0], pb[1]) <= self.radius_m

    def neighbours(self, robot_id: str) -> list[str]:
        """Peers within range, nearest first then by id for determinism."""
        origin = self._positions.get(robot_id)
        if origin is None:
            return []
        out: list[tuple[float, str]] = []
        for rid, pos in self._positions.items():
            if rid == robot_id or rid in self._quarantined:
                continue
            # A silenced peer cannot hear this robot, so it is not a neighbour.
            # Filtering here rather than in _deliver keeps the `reached` count
            # in broadcast() honest: nothing was reached, so nothing is counted.
            if rid in self._silenced:
                continue
            if self._crosses_partition(robot_id, rid):
                continue
            d = euclidean(origin[0], origin[1], pos[0], pos[1])
            if d <= self.radius_m:
                out.append((d, rid))
        out.sort()
        return [rid for _, rid in out]

    # ------------------------------------------------------------------
    # radio blackout (X-01)
    # ------------------------------------------------------------------
    def silence(self, robot_id: str) -> None:
        """Cut one robot's radio in BOTH directions.

        Symmetry is the point. A one-way cut would leave the robot still
        hearing peers and so still able to coordinate, which is not the failure
        being modelled: a jammed or shadowed antenna neither transmits nor
        receives, and that is precisely the case sovereign mode must survive.
        """
        self._silenced.add(robot_id)

    def restore(self, robot_id: str) -> bool:
        """Bring a silenced radio back. Returns whether one was actually out."""
        was_out = robot_id in self._silenced
        self._silenced.discard(robot_id)
        return was_out

    def is_silenced(self, robot_id: str) -> bool:
        return robot_id in self._silenced

    @property
    def silenced(self) -> tuple[str, ...]:
        return tuple(sorted(self._silenced))

    def degree(self) -> dict[str, int]:
        """Neighbour count per robot. The direct measure of coordination fan-out."""
        return {rid: len(self.neighbours(rid)) for rid in sorted(self._positions)}

    # ------------------------------------------------------------------
    # quarantine (X-10)
    # ------------------------------------------------------------------
    def quarantine(self, robot_id: str) -> None:
        """Stop accepting traffic from a robot judged to be misbehaving.

        Containment, not deletion: the robot still exists physically and the
        arbiter still routes other robots around it. Silencing a liar's
        COORDINATION voice while continuing to respect its BODY is the whole
        distinction that makes this safe.
        """
        self._quarantined.add(robot_id)

    def release_quarantine(self, robot_id: str) -> bool:
        """Lift a quarantine. Returns whether one was actually in force."""
        was_held = robot_id in self._quarantined
        self._quarantined.discard(robot_id)
        return was_held


    def is_quarantined(self, robot_id: str) -> bool:
        return robot_id in self._quarantined

    @property
    def quarantined(self) -> tuple[str, ...]:
        return tuple(sorted(self._quarantined))

    # ------------------------------------------------------------------
    # delivery
    # ------------------------------------------------------------------
    def _deliver(self, recipient: str, msg: CoordinationMessage, *, tick: int) -> None:
        """Apply the link model to one (already in-range) hop."""
        p = self.profile

        if p.loss_pct > 0.0 and self.rng.random() * 100.0 < p.loss_pct:
            self.stats.dropped += 1
            return

        if p.latency_ticks > 0:
            self._pending.setdefault(tick + p.latency_ticks, []).append(
                (recipient, msg)
            )
            self.stats.delayed += 1
            return

        self._inbox.setdefault(recipient, []).append(msg)
        self.stats.delivered += 1

        if p.duplicate_pct > 0.0 and self.rng.random() * 100.0 < p.duplicate_pct:
            self._inbox[recipient].append(msg)
            self.stats.duplicated += 1
            self.stats.delivered += 1

    def send(
        self, msg: CoordinationMessage, target_id: str, *, tick: int
    ) -> bool:
        """Unicast. Returns whether the hop was even attempted.

        False means the pair is out of range or quarantined - a refusal by the
        radio, distinct from a message that was sent and then lost, which
        returns True and shows up in `dropped`.
        """
        self.stats.offered += 1
        sender = msg.sender_id
        if sender in self._quarantined or target_id in self._quarantined:
            self.stats.quarantined += 1
            return False
        if not self.in_range(sender, target_id):
            self.stats.out_of_range += 1
            return False
        self._deliver(target_id, msg, tick=tick)
        return True

    def broadcast(self, msg: CoordinationMessage, *, tick: int) -> int:
        """Local broadcast: every in-range peer, each hop judged separately.

        "Broadcast" here means one radio emission reaching whoever is close
        enough, so the sender is charged ONE offered message regardless of how
        many peers hear it. Charging per recipient would make the X-03 counter
        grow with fleet density for a reason that has nothing to do with the
        coordination design.
        """
        self.stats.offered += 1
        sender = msg.sender_id
        if sender in self._quarantined:
            self.stats.quarantined += 1
            return 0
        if sender in self._silenced:
            # Charged as a drop, not as a quarantine: the message was offered
            # and lost to a fault, which is exactly what `dropped` means.
            self.stats.dropped += 1
            return 0

        reached = 0
        for rid in self.neighbours(sender):
            if self.profile.asymmetric and not self.in_range(rid, sender):
                self.stats.out_of_range += 1
                continue
            before = self.stats.delivered
            self._deliver(rid, msg, tick=tick)
            if self.stats.delivered > before or self.profile.latency_ticks > 0:
                reached += 1
        return reached

    def receive(self, robot_id: str) -> list[CoordinationMessage]:
        """Drain one robot's inbox. Ordering is arrival order, duplicates kept.

        Duplicates are NOT filtered here. Idempotence is the protocol's job,
        and hiding repeats at the transport would make a protocol that cannot
        tolerate them look correct.
        """
        return self._inbox.pop(robot_id, [])

    def tick_begin(self, tick: int) -> None:
        """Release messages whose delay expires at this tick. Call once per tick."""
        self.stats.ticks += 1
        for recipient, msg in self._pending.pop(tick, []):
            self._inbox.setdefault(recipient, []).append(msg)
            self.stats.delivered += 1

    def clear(self) -> None:
        self._inbox.clear()
        self._pending.clear()


@dataclass
class _PeerBeat:
    last_seen_s: float
    health: PeerHealth = PeerHealth.ALIVE
    misses: int = 0
    confirmed_at_s: Optional[float] = None


@dataclass
class FailureEvent:
    """A health transition worth telling the rest of the system about."""

    robot_id: str
    sim_time: float
    previous: PeerHealth
    current: PeerHealth

    def as_dict(self) -> dict:
        return {
            "robot_id": self.robot_id,
            "sim_time": round(self.sim_time, 3),
            "previous": self.previous.value,
            "current": self.current.value,
        }


class FailureDetector:
    """Heartbeat-based liveness tracking with a two-stage verdict (X-23).

    The ladder is ALIVE -> SUSPECTED -> FAILED, and only the last rung
    authorises anyone to release a peer's reservations. That gap is the whole
    design: under a degraded radio a single-stage detector declares healthy
    robots dead, frees the corridor they are still driving down, and manufactures
    the collision it was installed to prevent. Suspicion is cheap and
    recoverable; confirmation is expensive and acted upon.

    Recovery is explicit. A peer heard from again returns to ALIVE and the
    transition is reported, so a transient radio outage does not permanently
    strike robots off the roster.
    """

    def __init__(
        self,
        *,
        suspect_after_s: float = HEARTBEAT_TIMEOUT_S,
        confirm_after_s: float = CONFIRM_TIMEOUT_S,
    ) -> None:
        if confirm_after_s < suspect_after_s:
            raise ValueError(
                "confirm_after_s must be at least suspect_after_s: confirming a "
                "failure sooner than suspecting one makes the ladder meaningless"
            )
        self.suspect_after_s = float(suspect_after_s)
        self.confirm_after_s = float(confirm_after_s)
        self._peers: dict[str, _PeerBeat] = {}
        self.events: list[FailureEvent] = []

    def heartbeat(self, robot_id: str, sim_time: float) -> None:
        """Record that a peer was heard from at sim_time."""
        entry = self._peers.get(robot_id)
        if entry is None:
            self._peers[robot_id] = _PeerBeat(last_seen_s=float(sim_time))
            return
        previous = entry.health
        entry.last_seen_s = float(sim_time)
        entry.misses = 0
        entry.health = PeerHealth.ALIVE
        entry.confirmed_at_s = None
        if previous is not PeerHealth.ALIVE:
            self.events.append(
                FailureEvent(robot_id, float(sim_time), previous, PeerHealth.ALIVE)
            )

    def observe(self, robot_ids: Iterable[str], sim_time: float) -> None:
        """Convenience: heartbeat a whole batch of peers heard this tick."""
        for rid in robot_ids:
            self.heartbeat(rid, sim_time)

    def evaluate(
        self, sim_time: float, *, hold: Iterable[str] = (),
        revive: Iterable[str] = (),
    ) -> list[FailureEvent]:
        """Advance every peer's health and return this tick's transitions.

        Iterates in sorted id order so the event list is identical across runs
        of the same seed, which keeps the trace hash stable.

        `hold` (batch 2) names peers whose silence is NOT evidence of death -
        typically one nobody who could hear it can currently see, i.e. it has
        simply driven out of radio range, or one that is seen still moving.
        Such a peer can be SUSPECTED but is never confirmed FAILED while it is
        held. Silence alone cannot tell "gone away" from "gone dead", and
        confirming the former as the latter was measured producing FAILED
        verdicts in runs where no robot had failed at all.

        `revive` names silent peers there is positive evidence are alive (seen
        moving). A confirmed failure is normally sticky, but not against that
        evidence: such a peer drops back to SUSPECTED.
        """
        held = frozenset(hold) | frozenset(revive)
        revived = frozenset(revive)
        out: list[FailureEvent] = []
        for rid in sorted(self._peers):
            entry = self._peers[rid]
            silence = float(sim_time) - entry.last_seen_s
            previous = entry.health

            if silence >= self.confirm_after_s and (
                rid not in held
                or (previous is PeerHealth.FAILED and rid not in revived)
            ):
                # Once confirmed, a still-silent peer stays FAILED even if it
                # later drops out of sight; only hearing it again revives it.
                nxt = PeerHealth.FAILED
            elif silence >= self.confirm_after_s:
                nxt = PeerHealth.SUSPECTED
            elif silence >= self.suspect_after_s:
                nxt = PeerHealth.SUSPECTED
            else:
                nxt = PeerHealth.ALIVE

            if nxt is not previous:
                entry.health = nxt
                if nxt is PeerHealth.FAILED:
                    entry.confirmed_at_s = float(sim_time)
                event = FailureEvent(rid, float(sim_time), previous, nxt)
                out.append(event)
                self.events.append(event)

        return out

    def health(self, robot_id: str) -> PeerHealth:
        entry = self._peers.get(robot_id)
        return entry.health if entry else PeerHealth.UNKNOWN

    def confirmed_failed(self) -> tuple[str, ...]:
        """Peers it is safe to garbage-collect. Sorted, so callers are stable."""
        return tuple(
            rid for rid in sorted(self._peers)
            if self._peers[rid].health is PeerHealth.FAILED
        )

    def suspected(self) -> tuple[str, ...]:
        return tuple(
            rid for rid in sorted(self._peers)
            if self._peers[rid].health is PeerHealth.SUSPECTED
        )

    def alive(self) -> tuple[str, ...]:
        return tuple(
            rid for rid in sorted(self._peers)
            if self._peers[rid].health is PeerHealth.ALIVE
        )

    def forget(self, robot_id: str) -> bool:
        return self._peers.pop(robot_id, None) is not None

    def stats(self) -> dict:
        return {
            "tracked": len(self._peers),
            "alive": len(self.alive()),
            "suspected": len(self.suspected()),
            "failed": len(self.confirmed_failed()),
            "transitions": len(self.events),
            "suspect_after_s": self.suspect_after_s,
            "confirm_after_s": self.confirm_after_s,
        }

    def clear(self) -> None:
        self._peers.clear()
        self.events.clear()

# File contains AI-generated response based on internal company sources
