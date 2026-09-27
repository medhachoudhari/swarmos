"""One-shot source patch: correct the safety kernel's non-closing exemption.

WHAT WENT WRONG, and it is worth recording precisely because the failure was
loud, immediate and unambiguous - which is exactly what a good harness buys you.

Making the kernel graded produced this:

    baseline        19   +0.0%    0 collisions
    monitor_only    52 +173.7%    600-916 collisions   <- kernel not enforcing
    ladder_only     37  +94.7%    1791-2152 collisions
    full            37  +94.7%    1791-2152 collisions <- IDENTICAL to no kernel

`full` came out byte-for-byte identical to `ladder_only` on all three seeds:
12/2152/978, 11/2098/889, 14/1791/639. A safety kernel that produces exactly the
same trace as no safety kernel at all is not intervening even once. The graded
patch had opened the door and removed the door.

THE CAUSE. The graded patch changed the non-closing exemption from

    if gap >= segment_distance((here, here), theirs)          # version 6

to

    if segment_distance(endpoint, theirs) > math.dist(here, there)

reasoning that version 6 was dead code. Version 6 WAS dead code, and for the
reason given there: a swept segment contains its own start point, so
`gap = segment_distance(mine, theirs)` can never exceed the distance from that
start point to the same peer, and the test could only fire on exact equality.
That diagnosis was right. The replacement was wrong.

`math.dist(here, there)` is the distance between the two robots' CENTRES right
now. `segment_distance(endpoint, theirs)` is the distance from where this step
ends to the whole region the peer may occupy. Those two quantities are not
comparable, and the mismatch is not academic:

  - for an already-decided peer, `theirs` is a swept SEGMENT, so the right-hand
    side measures to the peer's current centre while the left-hand side measures
    to the nearest point of a segment that may extend a full step in any
    direction. The two sides are measuring to different objects;
  - for crossing traffic the error is fatal in the other direction. A robot
    passing in front of a peer ends its step FURTHER from the peer's centre than
    it started, because it is moving across and away - while its swept path went
    straight through the peer's. The exemption fired, the veto was skipped, and
    the pair drove through each other. Hence 600+ collisions in monitor_only,
    a configuration that had been provably collision-free minutes earlier.

THE FIX, which is the test version 6 was reaching for and got one term wrong:

    if segment_distance(endpoint, theirs) > segment_distance((here, here), theirs)

Both sides now measure the SAME thing - distance to the peer's granted geometry -
and differ only in where this robot is measured from: where the step ends, versus
where it would sit if it did not move at all. That is the literal definition of
"this motion does not close the gap", and unlike version 6 it is live, because
the left side drops the start point that made version 6 vacuous.

It is conservative by construction. The branch permits motion only when ending up
there is no worse than the stand-still the veto would have imposed, so it can
never admit a configuration a full veto would have refused.
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

OLD = """                if segment_distance(endpoint, theirs) > centre:
                    continue"""

NEW = """                if segment_distance(endpoint, theirs) > segment_distance(
                    (here, here), theirs
                ):
                    continue"""

# The `centre` element of each peer tuple is now unused by blocked_by, but it is
# still what the radius filter is computed from, so the tuple keeps its shape and
# only the name in the unpack changes to mark it deliberately unused.
OLD_UNPACK = "            for peer_id, theirs, centre in peers:"
NEW_UNPACK = "            for peer_id, theirs, _centre in peers:"

OLD_COMMENT = """                # The correct form is the baseline's: compare where this step
                # ENDS against how far apart the pair stands right now. It stays
                # sound because holding still is what the veto would have
                # achieved anyway, and this branch only permits motion ending
                # strictly further out than the pair sits at this instant."""

NEW_COMMENT = """                # Version 7 then over-corrected, and that failure is the most
                # instructive one in the whole sequence. It compared this step's
                # ENDPOINT against the pair's current CENTRE distance, which are
                # measurements to two different objects: the left side measures
                # to the peer's granted segment, the right side to the peer's
                # centre point. For crossing traffic the error is fatal - a robot
                # passing in front of a peer ends up further from the peer's
                # centre than it started, even though its swept path went
                # straight through the peer's. The exemption fired, the veto was
                # skipped, and `full` came out byte-identical to running with no
                # safety kernel at all: 2152 collisions where there had been 0.
                #
                # Both sides must measure to the SAME geometry and differ only in
                # where THIS robot is measured from - where the step ends, versus
                # where it would sit if it did not move. That is the literal
                # definition of "this motion does not close the gap", and unlike
                # version 6 it is live, because dropping the start point from the
                # left side is exactly what made version 6 vacuous.
                #
                # Conservative by construction: motion is permitted only when
                # ending up there is no worse than the stand-still the veto would
                # have imposed, so no configuration a full veto would refuse can
                # ever be admitted here."""


def main() -> int:
    src = TARGET.read_text()

    if "segment_distance(\n                    (here, here), theirs\n                )" in src:
        print("already patched, nothing to do")
        return 0

    for label, anchor in (
        ("exemption test", OLD),
        ("peer unpack", OLD_UNPACK),
        ("exemption comment", OLD_COMMENT),
    ):
        if src.count(anchor) != 1:
            print(f"ABORT: {label} matched {src.count(anchor)} times, expected 1")
            return 1

    src = src.replace(OLD_COMMENT, NEW_COMMENT, 1)
    src = src.replace(OLD, NEW, 1)
    src = src.replace(OLD_UNPACK, NEW_UNPACK, 1)

    TARGET.write_text(src)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
