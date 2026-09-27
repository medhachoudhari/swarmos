#!/usr/bin/env python3
"""Revert the no-yield-to-stationary change. It was measured and it lost.

MEASURED RESULT (rush_50, fleet 24, 900 ticks, seeds 11/13/17, total completions):

  config         before  after
  baseline           19     19
  monitor_only       13     13   (untouched, as expected - no ladder)
  ladder_only        37     17   <-- lost 20 completions
  full               13     11   <-- lost 2

The hypothesis was that yielding to an already-stopped peer was pure waste and
that routing around it would free the fleet. The hypothesis was WRONG, and the
control configuration proves it cleanly: ladder_only more than halved, and
ladder_only does not even have a safety kernel, so the holding bit it reacts to
comes only from its own YIELD and REROUTE rungs.

WHY IT LOST. Replacing a YIELD with a REROUTE trades a cheap, local, one-tick
wait for an expensive global replan. The engine's REROUTE handling clears the
path and feeds the blocker's cell in as a temporary obstacle, so the robot gets a
genuinely longer route - and in a dense aisle the detour immediately meets other
robots, which are also holding, which triggers another REROUTE. The livelock was
not removed, it was made more expensive: instead of pairs waiting one tick for
each other, robots now continuously re-plan around each other and never converge.
Collisions in ladder_only also went UP on seed 17 (1 -> 8), because a freshly
replanned path has a new heading that no peer was cleared against.

The deeper lesson, which is worth more than the patch: a YIELD against a
stationary peer is not waste. It is the mechanism by which a wedge RESOLVES.
One robot holds still, the other eventually wins the contest on its aging term
and moves through, and the pair unwinds in a few ticks. Aging is what guarantees
that, and the earlier leg deliberately built AGING_CAP_TICKS and STREAK_DECAY to
make it work. Bypassing the contest also bypassed the anti-starvation guarantee.

So the throughput problem is NOT that the ladder yields too readily. The real
gap, still unexplained, is why the ladder issues 3.1x more YIELDs when the
monitor is enabled. That observation stands and remains the thing to chase - but
the fix has to preserve the contest, not route around it.

Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "app" / "coordination" / "swarm_policy.py"

SENTINEL = "peer_holding"

ENC_NEW = """    peer_id: str
    distance: float
    following: bool
    peer_failed: bool = False
    # The peer declared itself held on its last tick. Such a peer is treated as
    # an obstacle to route around rather than as a party to negotiate with; see
    # tools/patch_no_yield_to_stationary.py for the measurement behind this.
    peer_holding: bool = False
"""
ENC_OLD = """    peer_id: str
    distance: float
    following: bool
    peer_failed: bool = False
"""

BUILD_NEW = """                worst = _Encounter(
                    peer_id=peer_id, distance=d, following=following,
                    peer_failed=failed, peer_holding=bool(view.holding),
                )
"""
BUILD_OLD = """                worst = _Encounter(
                    peer_id=peer_id, distance=d, following=following,
                    peer_failed=failed,
                )
"""


def main() -> int:
    text = TARGET.read_text()

    if SENTINEL not in text:
        print("no-yield-to-stationary already reverted - nothing to do")
        return 0

    # Remove the whole `if enc.peer_holding:` branch. It runs from its own line
    # up to the line that begins the next branch, which must survive.
    open_line = "        if enc.peer_holding:\n"
    after = "        if enc.distance >= CONFLICT_M:\n"
    if open_line not in text:
        print("ERROR: peer_holding branch not found, aborting", file=sys.stderr)
        return 1
    start = text.index(open_line)
    end = text.index(after, start)
    text = text[:start] + text[end:]

    text = text.replace(ENC_NEW, ENC_OLD, 1)
    text = text.replace(BUILD_NEW, BUILD_OLD, 1)

    if SENTINEL in text:
        print("ERROR: peer_holding still present after revert", file=sys.stderr)
        return 1
    if text.count("return self._contest(rid, me, enc, inbox)") != 1:
        print("ERROR: contest call not intact, aborting", file=sys.stderr)
        return 1
    if "if enc.distance >= CONFLICT_M:" not in text:
        print("ERROR: crossing branch lost, aborting", file=sys.stderr)
        return 1

    TARGET.write_text(text)
    print("reverted no-yield-to-stationary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
