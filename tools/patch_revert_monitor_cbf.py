"""Revert tools/patch_monitor_cbf.py. MEASURED AND REJECTED.

Result (rush_50, fleet 24, 900 ticks, seeds 11/13/17), against the now-honest
edge-triggered collision metric:

    config          completions          collisions per seed
    baseline        19    +0.0%          0 / 0 / 0
    monitor_only    13 -> 15  (-21.1%)   0/1/1  ->  5 / 3 / 4
    ladder_only     37 (unchanged)       54 / 72 / 47
    full            13 -> 14  (-26.3%)   0/0/0  ->  3 / 4 / 1

Throughput gain was one completion across three seeds, i.e. noise, and the price
was breaking the one result that was actually good: `full` was collision-free on
every seed and is no longer. Zero collisions is a hard success criterion, so this
is not a trade worth making at any throughput.

WHY IT WAS UNSOUND - and this is version 3's lesson in disguise, which is the
part worth keeping.

segment_distance is time-agnostic ON PURPOSE. It minimises over the two robots'
times INDEPENDENTLY, so it reports a breach whenever the two swept paths come
close in SPACE, regardless of when each robot is where. That looks needlessly
pessimistic and it is exactly what makes it sound.

The swept-minimum test parameterised both robots by a shared time in [0,1] and
so could permit a crossing on the grounds that the pair passes through the shared
space at DIFFERENT MOMENTS. That conclusion is only valid if the peer really does
traverse its granted segment at the assumed rate, and frequently it does not: it
may be replanned, it may run out of path, or its own monitor may clamp it after
this robot was already decided. The `granted` map is an intent, not a contract.

So the same rule applies as to version 3: a safety kernel may assume a peer will
OCCUPY space, never that it will VACATE it - and "it will be somewhere else by
the time I get there" is a vacating assumption with extra arithmetic.

WHAT SURVIVES THIS EXPERIMENT. The diagnosis that motivated it is still correct
and still unfixed: swept(scale) always contains `here`, so

    segment_distance(swept(scale), theirs) <= segment_distance((here,here), theirs)

and therefore once a pair is inside HARD_STOP_M no fraction of the step can clear
the floor. The graded MONITOR_SCALES fallback really is dead in the case it was
built for, which is the measured clamp ratio of 0.038 to 0.270. That defect is
real. This particular fix for it is not. Any future attempt must stay
time-agnostic.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

MARKER = "dpx * dvx + dpy * dvy"

START = "        # Collect the peers close enough to matter ONCE"
END = "        # Largest fraction of the requested step that still clears the floor."

# Verbatim text as it stood before patch_monitor_cbf.py.
ORIGINAL = '''        # Collect the peers close enough to matter ONCE, rather than re-walking
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
                #
                # It is deliberately TIME-AGNOSTIC: it minimises over the two
                # robots' times independently, so it reports a breach whenever
                # the paths come close in SPACE, whoever gets there first. A
                # time-parameterised version was measured and REJECTED - see
                # tools/patch_revert_monitor_cbf.py - because concluding "we pass
                # at different moments" assumes the peer will VACATE the space on
                # schedule, and `granted` is an intent rather than a contract.
                gap = segment_distance(mine, theirs)
                if gap >= HARD_STOP_M:
                    continue

                # NOTE there is deliberately NO "the gap is opening" exemption here.
                # Three versions of one were written and all three were wrong:
                # vacuous, then fail-open on centre-vs-segment distances, then
                # fail-open on crossing traffic even when gated on being inside
                # the floor. A robot cutting in front of a peer ends its step
                # further from that peer than it started while the two swept
                # paths pass straight through each other, so no endpoint test
                # can distinguish separating from crossing.
                #
                # Pairs that start inside the floor are un-wedged by
                # MONITOR_STUCK_TICKS instead: after 30 consecutively held ticks
                # the monitor issues a REROUTE, which is the same recovery
                # StopAndWaitPolicy uses and the reason monitor_only measured
                # byte-identical to the baseline. Recovery by replanning is
                # sound; recovery by relaxing the floor is not.
                #
                # KNOWN LIMITATION, measured and documented rather than fixed.
                # swept(scale) always contains `here`, so the gap above is
                # bounded by the standing-still gap for EVERY scale. Once a pair
                # is inside the floor no fraction of the step clears it, so the
                # graded MONITOR_SCALES fallback cannot fire and the clamp ratio
                # stays at 0.038 to 0.270 - almost every intervention is still a
                # full stop. Fixing it requires a tighter test that remains
                # time-agnostic; the obvious time-parameterised one costs
                # collisions. See tools/patch_revert_monitor_cbf.py.

                return (peer_id, gap)
            return None

'''

REST_DECL = "        full = project_step(me, MAX_STEP_M)\n"


def main() -> int:
    src = open(PATH).read()

    if MARKER not in src:
        try:
            ast.parse(src)
        except SyntaxError as exc:
            print(f"ABORT: marker absent but file broken: {exc}")
            return 1
        print("already reverted")
        return 0

    a = src.index(START)
    b = src.index(END)
    if b <= a:
        print("ABORT: end anchor precedes start anchor")
        return 1

    fixed = src[:a] + ORIGINAL + src[b:]

    # Restore the `rest` local the forward patch removed.
    if "rest: Segment = (here, here)" not in fixed:
        if REST_DECL not in fixed:
            print("ABORT: cannot find anchor to restore `rest`")
            return 1
        fixed = fixed.replace(
            REST_DECL, REST_DECL + "        rest: Segment = (here, here)\n", 1
        )

    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: reverted text does not parse: {exc}")
        return 1

    if MARKER in fixed:
        print("ABORT: rejected swept-minimum arithmetic survives")
        return 1
    if fixed.count("def blocked_by") != 1:
        print("ABORT: expected exactly one blocked_by")
        return 1
    if "return self._contest(rid, me, enc, inbox)" not in fixed:
        print("ABORT: contest tail call lost")
        return 1

    open(PATH, "w").write(fixed)
    print("reverted swept-minimum monitor, restored time-agnostic segment test")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
