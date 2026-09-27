#!/usr/bin/env python3
"""Remove the non-closing exemption from SwarmPolicy._monitor.

Measurement history for this one branch, all on rush_50 / fleet 24 / 900 ticks,
seeds 11,13,17:

  version 6  vacuous  (gap >= segment_distance(rest, theirs))   0 collisions,
             but the branch could never fire, so wedged pairs stayed wedged
  version 7  endpoint-vs-centre                                 600..916 collisions
  version 8  endpoint-vs-at_rest, gated on at_rest < HARD_STOP_M  1 and 3 collisions

Three attempts, three unsound or useless results. The branch is deleted. It was
only ever an optimisation - permission to keep moving while already inside the
floor - and the arbiter already has a correct, measured wedge-breaker in
MONITOR_STUCK_TICKS, which issues a REROUTE after 30 held ticks exactly as
StopAndWaitPolicy does. Correctness is not negotiable against throughput, and a
safety kernel that fails open is worse than no kernel at all, because it is
trusted.

The script is idempotent: if the branch is already gone it reports so and exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "app" / "coordination" / "swarm_policy.py"

# First line of the comment block that introduces the exemption.
OPEN = "                # Motion that does not CLOSE the gap is never vetoed, even from\n"
# The conditional itself, which is the last thing in the block.
COND = "                if at_rest < HARD_STOP_M and segment_distance(\n"
# The line that must follow the removed region.
AFTER = "                return (peer_id, gap)\n"

REPLACEMENT = """                # NOTE there is deliberately NO "the gap is opening" exemption here.
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
"""


def main() -> int:
    text = TARGET.read_text()

    if COND not in text:
        print("exemption already absent - nothing to do")
        return 0

    start = text.index(OPEN)
    # Cut forward to the line that must survive, so the whole comment block plus
    # the conditional plus its `continue` all go in one piece. Anchoring on the
    # following line rather than on the removed text avoids the mistake made by
    # patch_graded_monitor.py, which anchored a splice on text its own
    # replacement contained and silently destroyed the function.
    end = text.index(AFTER, start)

    patched = text[:start] + REPLACEMENT + "\n" + text[end:]

    if "at_rest < HARD_STOP_M" in patched:
        print("ERROR: conditional survived the splice, aborting", file=sys.stderr)
        return 1
    if patched.count("return (peer_id, gap)") != text.count("return (peer_id, gap)"):
        print("ERROR: return statement count changed, aborting", file=sys.stderr)
        return 1

    TARGET.write_text(patched)
    print(f"removed exemption: {len(text) - len(patched)} bytes net change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
