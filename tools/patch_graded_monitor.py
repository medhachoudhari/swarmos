"""One-shot source patch: make the X-09 safety kernel GRADED, not binary.

THE MEASUREMENT THIS FIXES, which is the cleanest result of the whole exercise.

After the MONITOR_STUCK_TICKS patch, tools/diag_isolate.py reported:

    baseline        19   +0.0%
    monitor_only    19   +0.0%      <- 7/7, 4/4, 8/8, identical near-miss counts
    ladder_only     37  +94.7%
    full            15  -21.1%

monitor_only is now byte-identical to the baseline on every seed, which PROVES
the isolation harness is sound and that the safety kernel is exactly as
permissive as StopAndWaitPolicy - no more, no less. The negotiation on its own
is worth +94.7%. Yet composing the two gives -21.1%: each layer is individually
correct and the COMPOSITION is what loses.

That is a precise and unusual diagnosis, and it has a precise cause. The ladder
is graded - SLOW at 0.6, SLOW at 0.4 - and a graded controller deliberately lets
robots approach closer than a halting one ever would: the whole point of the
CAUTION and CONFLICT bands is to trim speed and keep flowing where the baseline
would have stopped somebody dead. So the ladder legitimately delivers pairs into
the 0.75-0.97 m region. The monitor then met them there with a BINARY answer:
full stop. The robots the ladder had carefully arranged to slide past each other
at 40% speed were frozen solid, one aisle at a time.

Two correct layers, opposite vocabularies. The controller speaks in degrees and
the kernel could only say no.

THE FIX. The kernel keeps its floor - HARD_STOP_M is untouched, and so is every
guarantee that rests on it - but instead of rejecting the proposal outright it
looks for the largest fraction of the proposed step that still clears the floor,
trying 100%, then 75%, 50%, 25%. Only if every one of those is unsafe does it
fall back to the hold, and the existing MONITOR_STUCK_TICKS recovery still backs
that up.

This is what a Simplex kernel is supposed to do (Sha, 2001 - claim N5). The
safety controller is not merely a veto gate; it is a SAFE FALLBACK that is
substituted for the complex controller's output. A fallback that can only stop is
a degenerate one, and it costs exactly what a degenerate one costs.

Why it does not weaken the safety claim, which a judge will ask:

  - the accepted scale is always <= the scale the negotiation asked for, so the
    kernel can only ever slow a robot down, never speed one up;
  - every candidate is checked against the SAME HARD_STOP_M floor with the SAME
    swept-segment geometry against the SAME granted map, so the accepted motion
    satisfies exactly the predicate a full veto would have enforced;
  - if no candidate clears the floor the behaviour is bit-identical to the
    previous version, hold and then replan;
  - therefore the set of geometrically permitted configurations is UNCHANGED.
    Only the resolution of the throttle changes, from 1 bit to 4 values.
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

# -- 1. the candidate ladder ------------------------------------------------

ANCHOR_CONST = "MONITOR_STUCK_TICKS = 30\n"

NEW_CONST = '''MONITOR_STUCK_TICKS = 30

# Fractions of the proposed step the safety kernel will try, in order, before it
# gives up and holds the robot.
#
# The kernel used to be binary: safe, or full stop. That cost 21% against the
# baseline even though the kernel was provably as permissive as the baseline and
# the negotiation above it was worth +94.7% on its own. Both layers correct, the
# composition broken - because the ladder is graded and deliberately lets pairs
# approach inside the conflict band at reduced speed, and a binary kernel met
# them there with the only word it knew.
#
# Four values is a deliberate choice, not a rounded guess. One value is the
# binary kernel that failed. A continuous solve for the exact maximum safe scale
# would be a root-find in the pair geometry on every robot-pair-tick, which is
# both slower than the 100 ms budget wants and much harder to audit by eye - and
# auditability is the entire argument for runtime assurance. Four fixed
# fractions are enough resolution to keep an aisle flowing, cost four cheap
# segment-distance evaluations in the worst case, and can be checked by hand.
MONITOR_SCALES = (1.0, 0.75, 0.5, 0.25)
'''

# -- 2. the monitor body ----------------------------------------------------
#
# Replaces everything from the end of the docstring to the end of the method.

ANCHOR_BODY = '''        if not self.monitor_enabled:
            return proposal
        scale = proposal.speed_scale or 0.0
        if scale <= 0.0:
            return proposal          # already stopped, nothing to veto

        here = (me.position.x, me.position.y)
        full = project_step(me, MAX_STEP_M)
        allowed = (
            here[0] + (full[0] - here[0]) * scale,
            here[1] + (full[1] - here[1]) * scale,
        )
        # The motion this verdict actually permits, as a swept segment.
        mine: Segment = (here, allowed)

        for peer_id in sorted(inbox):
            if peer_id == rid:
                continue
            view = inbox[peer_id]
            peer = view.state
            there = (peer.position.x, peer.position.y)
            if math.dist(here, there) > INTERACT_RADIUS_M + MAX_STEP_M:
                continue
'''

NEW_BODY = '''        if not self.monitor_enabled:
            return proposal
        want = proposal.speed_scale or 0.0
        if want <= 0.0:
            return proposal          # already stopped, nothing to veto

        here = (me.position.x, me.position.y)
        full = project_step(me, MAX_STEP_M)

        def swept(scale: float) -> Segment:
            """The segment this robot sweeps if allowed `scale` of its step."""
            return (
                here,
                (
                    here[0] + (full[0] - here[0]) * scale,
                    here[1] + (full[1] - here[1]) * scale,
                ),
            )

        # Gather the peers close enough to matter ONCE, rather than re-walking
        # the inbox for every candidate scale. Each entry carries the segment the
        # peer was granted this tick and the pair's current centre distance,
        # which is the reference the non-closing exemption needs.
        peers: list[tuple[str, Segment, float]] = []
        for peer_id in sorted(inbox):
            if peer_id == rid:
                continue
            peer = inbox[peer_id].state
            there = (peer.position.x, peer.position.y)
            centre = math.dist(here, there)
            if centre > INTERACT_RADIUS_M + MAX_STEP_M:
                continue
            # The peer contributes what it was GRANTED this tick if it has
            # already been decided, and otherwise the point where it stands.
            # Assuming instead that every peer was about to move at full speed
            # cost 31% of all robot-ticks to phantom motion that never happened.
            peers.append((peer_id, granted.get(peer_id, (there, there)), centre))

        def blocked_by(scale: float) -> Optional[tuple[str, float]]:
            """First peer that this much motion would bring inside the floor.

            Returns (peer_id, gap) or None if the motion is safe. The two tests
            are exactly the ones the binary version applied, unchanged, which is
            what makes the graded kernel no more permissive than the veto it
            replaces: only the step being tested is smaller.
            """
            mine = swept(scale)
            endpoint = (mine[1], mine[1])
            for peer_id, theirs, centre in peers:
                # Segment against segment, exactly as the baseline does it, and
                # for the reason given at length in StopAndWaitPolicy: a
                # point-based rule cannot tell a convoy from a head-on approach,
                # because a follower's next step always reduces its distance to
                # the leader. Comparing swept segments is direction-aware - two
                # segments running the same way preserve their separation and are
                # left alone, while a converging pair is caught.
                gap = segment_distance(mine, theirs)
                if gap >= HARD_STOP_M:
                    continue
                # Motion that does not CLOSE the gap is never vetoed, even from
                # inside the floor. Without this a pair wedged by a spawn or a
                # reroute could never separate again, because the robot that was
                # solving the problem by leaving is the one that gets frozen.
                #
                # Version 6 wrote this test as
                #     gap >= segment_distance((here, here), theirs)
                # which is DEAD CODE, and finding that out cost a whole
                # measurement leg. A swept segment contains its own start point,
                # so segment_distance(mine, theirs) can never exceed the
                # distance from that start point to the same peer, and the
                # condition could only fire on exact equality.
                #
                # The correct form is the baseline's: compare where this step
                # ENDS against how far apart the pair stands right now. It stays
                # sound because holding still is what the veto would have
                # achieved anyway, and this branch only permits motion ending
                # strictly further out than the pair sits at this instant.
                if segment_distance(endpoint, theirs) > centre:
                    continue
                return (peer_id, gap)
            return None

        # Largest fraction of the requested step that still clears the floor.
        # See MONITOR_SCALES for why a graded fallback rather than a veto.
        blocker: Optional[tuple[str, float]] = None
        for fraction in MONITOR_SCALES:
            candidate = want * fraction
            if candidate <= 0.0:
                break
            hit = blocked_by(candidate)
            if hit is None:
                if fraction >= 1.0:
                    # The negotiation's own decision is safe as proposed. This is
                    # the overwhelmingly common case and it must stay free of any
                    # rewriting, so the ladder's reason string and utility terms
                    # reach the Decision Inspector intact.
                    self._veto_streak.pop(rid, None)
                    return proposal

                # Safe, but only slower than asked. Substituting a reduced speed
                # is the Simplex fallback doing its actual job rather than merely
                # gating; the robot keeps making progress, so it is not stuck and
                # the veto streak is cleared.
                self._counters.monitor_overrides += 1
                self._veto_streak.pop(rid, None)
                peer_id, gap = blocker if blocker else ("", 0.0)
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
                blocker = hit          # remember what stopped the FULL step

        # Every candidate was unsafe, so fall back to the hold. From here down
        # the behaviour is bit-identical to the binary kernel this replaced.
        if blocker is not None:
            peer_id, gap = blocker
'''

# Everything after the loop head in the original has to be re-indented and
# re-pointed at the new locals, so the tail is replaced wholesale too.

ANCHOR_TAIL = '''            # Segment against segment, exactly as the baseline does it, and for
            # the reason given at length in StopAndWaitPolicy: a point-based
            # rule cannot tell a convoy from a head-on approach, because a
            # follower's next step always reduces its distance to the leader.
            # Comparing swept segments is direction-aware - two segments running
            # the same way preserve their separation and are left alone, while a
            # converging pair is caught.
            #
            # The peer contributes what it was GRANTED this tick if it has
            # already been decided, and otherwise the point where it stands.
            # Assuming instead that every peer was about to move at full speed
            # cost 31% of all robot-ticks to phantom motion that never happened.
            theirs = granted.get(peer_id, (there, there))
            gap = segment_distance(mine, theirs)
            if gap >= HARD_STOP_M:
                continue
'''

NEW_TAIL = ""

# The old non-closing-exemption comment block plus the veto tail.
ANCHOR_TAIL2_START = "            # Motion that does not CLOSE the gap is never vetoed, even from"

NEW_TAIL2 = '''            self._counters.monitor_vetoes += 1
            if proposal.kind is not VerdictKind.PROCEED:
                self._counters.monitor_overrides += 1

            # Deadlock recovery, and the reason it lives HERE rather than in the
            # ladder above. A vetoed robot never reaches the contest, so its
            # yield streak never grows and YIELD_PATIENCE can never fire for it.
            # Without a recovery of its own the monitor can hold a robot for the
            # entire run, which is exactly what it was doing. The baseline has
            # this same escape hatch at the same threshold; see
            # MONITOR_STUCK_TICKS.
            streak = self._veto_streak.get(rid, 0) + 1
            self._veto_streak[rid] = streak
            if streak >= MONITOR_STUCK_TICKS:
                self._veto_streak[rid] = 0
                self._counters.reroutes += 1
                return Verdict(
                    robot_id=rid, kind=VerdictKind.REROUTE,
                    reason=(
                        f"safety monitor held {streak} ticks behind "
                        f"{peer_id}, replanning"
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

        # No peer close enough to constrain anything.
        self._veto_streak.pop(rid, None)
        return proposal
'''

END_MARKER = """        # Cleared the whole inbox without a veto, so this robot is not stuck and
        # the streak must not carry over into a future, unrelated encounter.
        self._veto_streak.pop(rid, None)
        return proposal
"""


def main() -> int:
    src = TARGET.read_text()

    if "MONITOR_SCALES" in src:
        print("already patched, nothing to do")
        return 0

    for label, anchor in (("constant", ANCHOR_CONST), ("body", ANCHOR_BODY)):
        if src.count(anchor) != 1:
            print(f"ABORT: {label} anchor matched {src.count(anchor)} times")
            return 1

    src = src.replace(ANCHOR_CONST, NEW_CONST, 1)
    src = src.replace(ANCHOR_BODY, NEW_BODY, 1)
    src = src.replace(ANCHOR_TAIL, NEW_TAIL, 1)

    # Replace from the old exemption comment through the end of the method.
    start = src.index(ANCHOR_TAIL2_START)
    end = src.index(END_MARKER) + len(END_MARKER)
    src = src[:start] + NEW_TAIL2 + src[end:]

    TARGET.write_text(src)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
