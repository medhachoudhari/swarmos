"""Replace the monitor's segment-distance test with an exact swept-minimum
separation test plus a non-degradation floor.

WHY. blocked_by() measured segment_distance(swept(scale), theirs). swept(scale)
runs from `here` to `here + scale*step`, so it ALWAYS contains `here`, and
therefore

    segment_distance(swept(scale), theirs) <= segment_distance((here,here), theirs)

for every scale. Call the right hand side at_rest. If at_rest < HARD_STOP_M then
the measured gap is below the floor for EVERY candidate scale, including the
smallest, so no fraction of the step can ever clear it. The graded MONITOR_SCALES
fallback is mathematically dead in exactly the situation it was built for, which
is why the measured clamp ratio was only 0.038 to 0.270: clamping succeeded only
for peers still approaching from OUTSIDE the floor, and every pair already inside
it got a full stop until MONITOR_STUCK_TICKS fired 3 seconds later.

This is the same "a swept segment contains its own start point" defect the
_monitor docstring already records for version 2. The rewrite inherited it.

WHAT REPLACES IT. Two changes, both narrowing the measurement rather than
relaxing the rule.

1. Exact minimum separation over the tick instead of segment-to-segment
   distance. The distance between two points moving in straight lines is a
   CONVEX function of time, so its minimum over the tick is at an endpoint or at
   the single interior stationary point, which has a closed form. This is
   strictly more correct than segment_distance, which minimises over the two
   times INDEPENDENTLY and so vetoes robots that pass through the same space at
   different moments. It is also what closes the hole that made version 3's
   endpoint-only test fail open on crossing traffic: an interior minimum is
   computed, not sampled.

2. The floor is never stricter than the separation the pair ALREADY has:

       limit = min(now, HARD_STOP_M)

   When now >= HARD_STOP_M this is the original guarantee, unchanged. When
   now < HARD_STOP_M the constraint "stay outside the floor" is already violated
   and unsatisfiable, and holding does not restore it, it freezes the violation
   (the frozen-overlap case that the collision metric defect was hiding). Motion
   is then permitted only if separation never dips below what it is right now, so
   the pair cannot become physically closer than it already is and no new
   collision can be created.

   This is sound where the three rejected "the gap is opening" exemptions were
   not, because it bounds the ENTIRE trajectory rather than testing an endpoint.

The contest is untouched, so the anti-starvation guarantee that the rejected
no-yield-to-stationary patch destroyed is preserved.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

OLD_REST = """        rest: Segment = (here, here)

"""

START = "        # Collect the peers close enough to matter ONCE"
END = "        # Largest fraction of the requested step that still clears the floor."

NEW = '''        # Collect the peers close enough to matter ONCE, rather than
        # re-walking the inbox for each candidate scale. Each entry carries
        # where the peer starts, the displacement it was GRANTED this tick, and
        # the current centre-to-centre separation, which is the reference the
        # non-degradation floor below is measured against.
        Peer = tuple[str, tuple[float, float], tuple[float, float], float]
        peers: list[Peer] = []
        for peer_id in sorted(inbox):
            if peer_id == rid:
                continue
            peer = inbox[peer_id].state
            there = (peer.position.x, peer.position.y)
            now = math.dist(here, there)
            if now > INTERACT_RADIUS_M + MAX_STEP_M:
                continue
            # The peer contributes what it was GRANTED this tick if it has
            # already been decided, and otherwise the point where it stands.
            # Assuming instead that every peer was about to move at full speed
            # cost 31% of all robot-ticks to phantom motion that never happened.
            theirs = granted.get(peer_id, (there, there))
            their_delta = (
                theirs[1][0] - theirs[0][0],
                theirs[1][1] - theirs[0][1],
            )
            peers.append((peer_id, there, their_delta, now))

        def blocked_by(scale: float) -> Optional[tuple[str, float]]:
            """First peer that this much motion would bring too close.

            Returns (peer_id, min_separation), or None when the motion is safe.

            The previous version of this test measured
            segment_distance(swept(scale), theirs). That is unusable for a
            GRADED kernel, and the reason is arithmetic rather than tuning:
            swept(scale) always contains `here`, so the measured gap is bounded
            above by the standing-still gap for every scale. Once a pair was
            inside the floor, no fraction of the step could clear it and the
            graded fallback could never fire - measured clamp ratio 0.038 to
            0.270. Same start-point contamination the docstring records for
            version 2 of this rule.
            """
            my_delta = ((full[0] - here[0]) * scale, (full[1] - here[1]) * scale)
            for peer_id, there, their_delta, now in peers:
                # Exact minimum separation over this tick for two robots each
                # moving in a straight line. The distance between two linearly
                # moving points is CONVEX in time, so the minimum is either at
                # an endpoint or at the one interior stationary point, which
                # solves in closed form. Computing that interior point is what
                # closes the hole that made version 3 fail open: a robot cutting
                # across a peer can start far, end far, and still pass straight
                # through it in between, so no endpoint SAMPLE can see the
                # breach while this MINIMISATION always does.
                #
                # It is also strictly tighter in meaning than segment_distance,
                # which minimises over the two robots' times INDEPENDENTLY and
                # so reports a breach for two robots crossing the same square
                # metre several ticks apart.
                dpx, dpy = there[0] - here[0], there[1] - here[1]
                dvx = their_delta[0] - my_delta[0]
                dvy = their_delta[1] - my_delta[1]
                vv = dvx * dvx + dvy * dvy
                if vv <= 1e-18:
                    # No relative motion, so separation is constant across the
                    # tick. This is the convoy case, and it is why a queue at a
                    # steady gap is left alone instead of being vetoed on every
                    # tick forever.
                    t = 0.0
                else:
                    t = -(dpx * dvx + dpy * dvy) / vv
                    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                mins = math.hypot(dpx + t * dvx, dpy + t * dvy)

                # The floor, but never stricter than the separation the pair
                # ALREADY has. Two readings of one invariant:
                #
                #   now >= HARD_STOP_M: the original guarantee, unchanged. The
                #   motion may not bring the pair inside the floor at any moment
                #   during the tick. Approaching traffic is caught exactly as
                #   before.
                #
                #   now <  HARD_STOP_M: the pair is already inside the floor, so
                #   "stay outside it" is unsatisfiable, and a hold does not
                #   restore it - it freezes the violation in place. That frozen
                #   pair is the exact case the collision metric defect was
                #   hiding. Motion is therefore permitted only if the separation
                #   never dips below what it is right now, so the pair cannot
                #   become physically closer than it already is and no new
                #   collision can be created.
                #
                # Safety argument: min separation over the tick is bounded below
                # by min(now, HARD_STOP_M), so separation is non-increasing only
                # down to a bound the pair has already achieved. It can never
                # cross 0.70 m unless it was already there.
                limit = now if now < HARD_STOP_M else HARD_STOP_M
                if mins < limit - TIE_EPS:
                    return (peer_id, mins)
            return None

'''


def main() -> int:
    src = open(PATH).read()

    if "dpx * dvx + dpy * dvy" in src:
        print("already applied")
        return 0

    if START not in src or END not in src:
        print("ABORT: anchors not found")
        return 1

    a = src.index(START)
    b = src.index(END)
    if b <= a:
        print("ABORT: end anchor precedes start anchor")
        return 1

    fixed = src[:a] + NEW + src[b:]

    # `rest` was only the reference for the deleted at_rest term. Drop it rather
    # than leave a dead local in a file this heavily annotated.
    if OLD_REST in fixed:
        fixed = fixed.replace(OLD_REST, "", 1)

    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: result does not parse: {exc}")
        return 1

    # Guards. The kernel must still be a kernel.
    if "HARD_STOP_M" not in NEW:
        print("ABORT: floor vanished")
        return 1
    if fixed.count("def blocked_by") != 1:
        print("ABORT: expected exactly one blocked_by")
        return 1
    if "return self._contest(rid, me, enc, inbox)" not in fixed:
        print("ABORT: contest tail call lost")
        return 1

    open(PATH, "w").write(fixed)
    print("applied swept-minimum + non-degradation floor")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
