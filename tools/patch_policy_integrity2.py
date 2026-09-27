"""Stage 2: import, sign on broadcast, verify+audit on drain, GC on failure."""
import ast

POL = "app/coordination/swarm_policy.py"
src = open(POL).read()

# ---- import -----------------------------------------------------------------
old = """from app.coordination.messages import CoordinationMessage, MessageType
from app.coordination.models import AMRState, RobotStatus"""
new = """from app.coordination.integrity import (
    IntegrityVerdict,
    MessageAuthenticator,
    SentinelCouncil,
)
from app.coordination.messages import CoordinationMessage, MessageType
from app.coordination.models import AMRState, RobotStatus"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- sign on broadcast ------------------------------------------------------
old = """            )
            self.radio.broadcast(msg, tick=tick)
"""
new = """            )
            if self.integrity_enabled:
                # Signed BEFORE it enters the radio, because a signature applied
                # after transport would authenticate the transport rather than
                # the sender, which is the whole point of doing it at all.
                self.auth.sign(msg)
            self.radio.broadcast(msg, tick=tick)
"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- verify + audit on drain -----------------------------------------------
old = """            for msg in self.radio.receive(rid):
                if msg.type is not MessageType.ROBOT_STATE:
                    continue
                payload = msg.payload"""
new = """            for msg in self.radio.receive(rid):
                if msg.type is not MessageType.ROBOT_STATE:
                    continue
                if self.integrity_enabled:
                    verdict = self.auth.verify(msg)
                    if verdict != IntegrityVerdict.OK:
                        # Dropped AND reported. Silently discarding hostile
                        # traffic would make an active attack look exactly like
                        # a quiet radio, which is the one thing an operator must
                        # never be unable to tell apart.
                        self._counters.messages_rejected += 1
                        self.council.audit_signature(
                            accuser=rid, accused=msg.sender_id,
                            verdict=verdict, tick=tick,
                        )
                        continue
                payload = msg.payload"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- audit the claim, right after the view is stored ------------------------
old = """                    last_tick=msg.sequence,
                    heard_tick=tick,
                )

                self.detector.heartbeat(msg.sender_id, sim_time)
"""
new = """                    last_tick=msg.sequence,
                    heard_tick=tick,
                )

                if self.integrity_enabled:
                    # The behavioural check. What the peer SAYS (peer_state,
                    # which came from the peer) against what this robot SEES
                    # (self._sightings, which did not). A peer that is not in
                    # sight yields observed=None and is not accused of anything.
                    seen = self._sightings.get(rid, {}).get(msg.sender_id)
                    self.council.audit_claim(
                        accuser=rid,
                        accused=msg.sender_id,
                        claimed=(peer_state.position.x, peer_state.position.y),
                        observed=seen,
                        tick=tick,
                    )

                self.detector.heartbeat(msg.sender_id, sim_time)
"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- enforcement + GC, at the end of _drain_round --------------------------
old = """            if event.current is PeerHealth.FAILED:
                self._counters.failures_confirmed += 1
"""
new = """            if event.current is PeerHealth.FAILED:
                self._counters.failures_confirmed += 1

        if self.integrity_enabled:
            self._enforce_containment(tick)
        # Runs whether or not the integrity layer is on, because a robot that
        # simply DIED holding reserved space is the common case and leaks floor
        # area just as permanently as a contained one.
        self._reclaim_space()

    def _enforce_containment(self, tick: int) -> None:
        \"\"\"Apply the council's verdicts to the radio.

        The council decides and the radio enforces. Keeping them apart means the
        decision logic is testable with no radio at all, and the radio stays the
        single place where fleet connectivity is determined - two mechanisms that
        could each cut a robot off would eventually disagree.
        \"\"\"
        contained = set(self.council.contained)
        for rid in sorted(contained):
            if not self.radio.is_quarantined(rid):
                self.radio.quarantine(rid)
                self._counters.robots_contained += 1
                # A contained robot's declared intents are now worthless, and
                # its reserved space must not keep blocking honest robots.
                self._drop_peer_everywhere(rid)
        for rid in sorted(self.radio.quarantined):
            if rid not in contained:
                self.radio.release_quarantine(rid)
                self._reclaimed.discard(rid)
        self._counters.accusations_raised = len(self.council.accusation_log)

    def _drop_peer_everywhere(self, rid: str) -> None:
        \"\"\"Forget a contained robot's claims across every local view.

        Without this, the last thing a rogue said before being cut off would sit
        in every neighbour's inbox until STALE_TICKS expired it - the robot would
        be contained but its final lie would still be steering the fleet.
        \"\"\"
        for inbox in self._views.values():
            inbox.pop(rid, None)
        self._commit.pop(rid, None)
        self._yield_streak.pop(rid, None)

    def _reclaim_space(self) -> None:
        \"\"\"Release reservations held by robots that can no longer use them.

        ReservationManager.release_robot_reservations and
        FailureDetector.confirmed_failed both already existed, and nothing called
        one from the other. A confirmed-failed robot therefore held its reserved
        cells for the remainder of the run: a permanent loss of floor area that
        no counter would ever have shown, because nothing was counting.
        \"\"\"
        if self.reservations is None:
            return
        gone = set(self.detector.confirmed_failed()) | set(self.council.contained)
        for rid in sorted(gone - self._reclaimed):
            released = self.reservations.release_robot_reservations(rid)
            self._reclaimed.add(rid)
            self._counters.reservations_reclaimed += int(released or 0)
"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- observe() hook, and stats --------------------------------------------
old = """    # -- encounter search ---------------------------------------------------"""
new = """    def observe(self, sightings: dict) -> None:
        \"\"\"Hand the arbiter this tick's ground-truth sightings.

        Called by the simulation before arbitrate(). This is the ONE place the
        coordination layer receives information it did not get over the radio,
        and it exists because a claim can only be checked against something
        independent of the claimant - a detector that had to trust the message
        in order to check the message would verify nothing at all.
        \"\"\"
        self._sightings = sightings or {}

    # -- encounter search ---------------------------------------------------"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """            "radio": radio,
            "msgs_per_robot_tick": radio.get("msgs_per_robot_tick", 0.0),
        }"""
new = """            "radio": radio,
            "msgs_per_robot_tick": radio.get("msgs_per_robot_tick", 0.0),
            "integrity": {
                "enabled": self.integrity_enabled,
                "messages_rejected": c.messages_rejected,
                "accusations": c.accusations_raised,
                "robots_contained": c.robots_contained,
                "reservations_reclaimed": c.reservations_reclaimed,
                "auth": self.auth.stats.as_dict(),
                "council": self.council.stats(),
            },
        }"""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(POL, "w").write(src)
print("stage 2 OK")
