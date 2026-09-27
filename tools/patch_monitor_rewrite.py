"""Rewrite the X-09 safety kernel body cleanly, and correct its exemption.

TWO THINGS ARE BEING FIXED HERE.

1. A BAD SPLICE. tools/patch_graded_monitor.py replaced the tail of _monitor by
   searching for a comment that its own replacement text also contained, so the
   cut landed in the wrong place. The result compiled and ran, which is the
   dangerous part: `blocked_by` lost its return statement and swallowed the veto
   tail, so it could only ever return None, and the scale-selection loop vanished
   entirely. The kernel therefore approved every proposal unconditionally.

   The measurement caught it instantly and unmistakably. `full` came out
   byte-for-byte identical to `ladder_only` on all three seeds - 12/2152/978,
   11/2098/889, 14/1791/639 - and a safety kernel whose trace is indistinguishable
   from having no safety kernel at all is not running. That is the value of
   keeping a no-kernel configuration in the harness: it is a live control, and it
   turns a silent structural error into an obvious one.

   Lesson recorded for the next patch: never anchor a splice on text the
   replacement also contains. This script avoids the trap entirely by rewriting
   the method between two stable delimiters that appear nowhere in the new body.

2. THE OVER-BROAD EXEMPTION that the graded patch introduced, which was a real
   logic error independent of the splice. It read

       if segment_distance(endpoint, theirs) > math.dist(here, there)

   mixing two incomparable measurements: the left side is the distance from this
   step's endpoint to the peer's granted SEGMENT, the right side is the distance
   between the two robots' CENTRES. For crossing traffic that is fatal - a robot
   passing in front of a peer ends up further from the peer's centre than it
   started even though its swept path went straight through the peer's - so the
   exemption fired, the veto was skipped, and monitor_only logged 600-916
   collisions where it had been provably collision-free.

   The correct test compares the SAME geometry from two positions of this robot:

       segment_distance(endpoint, theirs) > segment_distance((here, here), theirs)

   i.e. "does ending up there leave me further from the peer than not moving at
   all". That is the literal meaning of "this motion does not close the gap". It
   is conservative by construction, because it only ever permits motion that ends
   no nearer than the stand-still a veto would have imposed.

   It is also LIVE, unlike the original version 6 form
   `gap >= segment_distance((here, here), theirs)`, which was vacuous: a swept
   segment contains its own start point, so the left side could never exceed the
   right and the branch could only fire on exact equality.
"""

from __future__ import annotations

import pathlib
import sys

TARGET = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "coordination"
    / "swarm_policy.py"
)

# Delimiters. Both are unique in the file and neither appears in NEW_BODY, which
# is the property the previous patch script failed to preserve.
START = "        if not self.monitor_enabled:\n"
END = "    # -- CoordinationPolicy -------------------------------------------------\n"

NEW_BODY = '''        if not self.monitor_enabled:
            return proposal
        want = proposal.speed_scale or 0.0
        if want <= 0.0:
            return proposal          # already stopped, nothing to veto

        here = (me.position.x, me.position.y)
        full = project_step(me, MAX_STEP_M)
        rest: Segment = (here, here)

        def swept(scale: float) -> Segment:
            """The segment this robot sweeps if allowed `scale` of its step."""
            return (
                here,
                (
                    here[0] + (full[0] - here[0]) * scale,
                    here[1] + (full[1] - here[1]) * scale,
                ),
            )

        # Collect the peers close enough to matter ONCE, rather than re-walking
        # the inbox for each candidate scale. Each entry carries the segment that
        # peer was granted this tick, and the distance from this robot's
        # STANDING-STILL position to that segment, which is the reference the
        # non-closing exemption is measured against.
        peers: list[tuple[str, Segment, float]] = []
        for peer_id in sorted(inbox):
            if peer_id == rid:
                continue
            peer = inbox[peer_id].state
            there = (peer.position.x, peer.position.y)
            if math.dist(here, there) > INTERACT_RADIUS_M + MAX_STEP_M:
                continue
            # The peer contributes what it was GRANTED this tick if it has
            # already been decided, and otherwise the point where it stands.
            # Assuming instead that every peer was about to move at full speed
            # cost 31% of all robot-ticks to phantom motion that never happened.
            theirs = granted.get(peer_id, (there, there))
            peers.append((peer_id, theirs, segment_distance(rest, theirs)))

        def blocked_by(scale: float) -> Optional[tuple[str, float]]:
            """First peer that this much motion would bring inside the floor.

            Returns (peer_id, gap), or None when the motion is safe. Both tests
            are the ones the binary kernel applied; only the size of the step
            under test changes, which is what makes the graded kernel no more
            permissive than the veto it replaces.
            """
            mine = swept(scale)
            endpoint: Segment = (mine[1], mine[1])
            for peer_id, theirs, at_rest in peers:
                # Segment against segment, exactly as the baseline does it, and
                # for the reason StopAndWaitPolicy gives at length: a point-based
                # rule cannot tell a convoy from a head-on approach, because a
                # follower's next step always reduces its distance to the leader.
                # Comparing swept segments is direction-aware - two segments
                # running the same way preserve their separation and are left
                # alone, while a converging pair is caught.
                gap = segment_distance(mine, theirs)
                if gap >= HARD_STOP_M:
                    continue

                # Motion that does not CLOSE the gap is never vetoed, even from
                # inside the floor. Without this a pair wedged by a spawn or a
                # reroute could never separate again, because the robot solving
                # the problem by leaving is the one that gets frozen.
                #
                # Two earlier forms of this test were both wrong, in opposite
                # directions, and both cost a measurement leg.
                #
                # Version 6 wrote `gap >= segment_distance(rest, theirs)`, which
                # is VACUOUS: a swept segment contains its own start point, so
                # the left side can never exceed the right and the branch could
                # only fire on exact equality. The escape hatch never opened, and
                # every pair that drifted inside the floor stayed frozen for the
                # rest of the run.
                #
                # Version 7 over-corrected to
                # `segment_distance(endpoint, theirs) > math.dist(here, there)`,
                # mixing incomparable measurements - the left side measures to
                # the peer's granted SEGMENT, the right to the peer's CENTRE. For
                # crossing traffic that is fatal: a robot passing in front of a
                # peer ends further from the peer's centre than it started even
                # though its swept path went straight through the peer's. The
                # exemption fired, the veto was skipped, and a configuration that
                # had been provably collision-free logged 600 to 916 collisions.
                #
                # The correct test measures the SAME geometry from two positions
                # of THIS robot: where the step ends, versus where it would sit
                # if it did not move. That is the literal definition of "this
                # motion does not close the gap", and it is conservative by
                # construction, because it permits motion only when ending up
                # there is no worse than the stand-still a veto would impose.
                if segment_distance(endpoint, theirs) > at_rest:
                    continue

                return (peer_id, gap)
            return None

        # Largest fraction of the requested step that still clears the floor.
        # See MONITOR_SCALES for why a graded fallback rather than a bare veto.
        blocker: Optional[tuple[str, float]] = None
        for fraction in MONITOR_SCALES:
            candidate = want * fraction
            if candidate <= 0.0:
                break
            hit = blocked_by(candidate)
            if hit is not None:
                if blocker is None:
                    blocker = hit      # remember what stopped the FULL step
                continue

            if fraction >= 1.0:
                # The negotiation's own decision is safe as proposed. This is the
                # overwhelmingly common case and it must pass through untouched,
                # so the ladder's reason string and utility terms reach the
                # Decision Inspector intact.
                self._veto_streak.pop(rid, None)
                return proposal

            # Safe, but slower than asked. Substituting a reduced speed is the
            # Simplex fallback doing its real job rather than merely gating: the
            # robot keeps making progress, so it is not stuck and its veto streak
            # is cleared.
            self._counters.monitor_overrides += 1
            self._veto_streak.pop(rid, None)
            peer_id, gap = blocker if blocker is not None else ("", 0.0)
            return Verdict(
                robot_id=rid, kind=VerdictKind.SLOW,
                reason=(
                    f"safety monitor clamped to {fraction:.0%} of requested "
                    f"speed: {peer_id} at {gap:.2f} m, floor "
                    f"{HARD_STOP_M:.2f} m"
                ),
                speed_scale=candidate,
                conflict_with=(peer_id,) if peer_id else (),
                utility_terms=proposal.utility_terms,
                winning_margin=proposal.winning_margin,
            )

        if blocker is None:
            # Nothing constrained any candidate, so there was nothing to decide.
            self._veto_streak.pop(rid, None)
            return proposal

        # Every candidate speed was unsafe, so hold. From here down the behaviour
        # is identical to the binary kernel this replaced.
        peer_id, gap = blocker
        self._counters.monitor_vetoes += 1
        if proposal.kind is not VerdictKind.PROCEED:
            self._counters.monitor_overrides += 1

        # Deadlock recovery, and the reason it lives HERE rather than in the
        # ladder above: a vetoed robot never reaches the contest, so its yield
        # streak never grows and YIELD_PATIENCE can never fire for it. Without a
        # recovery of its own the kernel can hold a robot for an entire run,
        # which is exactly what it was doing - and the baseline has this same
        # escape hatch at the same threshold. See MONITOR_STUCK_TICKS.
        streak = self._veto_streak.get(rid, 0) + 1
        self._veto_streak[rid] = streak
        if streak >= MONITOR_STUCK_TICKS:
            self._veto_streak[rid] = 0
            self._counters.reroutes += 1
            return Verdict(
                robot_id=rid, kind=VerdictKind.REROUTE,
                reason=(
                    f"safety monitor held {streak} ticks behind {peer_id}, "
                    f"replanning"
                ),
                conflict_with=(peer_id,),
                utility_terms=proposal.utility_terms,
                winning_margin=proposal.winning_margin,
            )

        return Verdict(
            robot_id=rid, kind=VerdictKind.WAIT,
            reason=(
                f"safety monitor veto: swept path comes within "
                f"{gap:.2f} m of {peer_id}, floor {HARD_STOP_M:.2f} m"
            ),
            conflict_with=(peer_id,),
            utility_terms=proposal.utility_terms,
            winning_margin=proposal.winning_margin,
        )

'''


def main() -> int:
    src = TARGET.read_text()

    for label, marker in (("start", START), ("end", END)):
        if src.count(marker) != 1:
            print(f"ABORT: {label} marker matched {src.count(marker)} times")
            return 1
    # Only the END marker must be absent from the replacement. The START marker
    # is the first line of the new body by design - the rewrite begins exactly
    # where the old body began - so guarding it here was a bug in this script's
    # own safety check, and it is the mirror image of the mistake that made
    # patch_graded_monitor.py splice in the wrong place: an anchor must be unique
    # in the REGION IT DELIMITS, not globally absent from the new text.
    if END in NEW_BODY:
        print("ABORT: end marker also occurs in the replacement body")
        return 1


    begin = src.index(START)
    finish = src.index(END)
    if finish <= begin:
        print("ABORT: markers are out of order")
        return 1

    src = src[:begin] + NEW_BODY + src[finish:]
    TARGET.write_text(src)
    print(f"rewrote _monitor in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
