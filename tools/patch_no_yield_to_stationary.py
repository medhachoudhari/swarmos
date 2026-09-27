#!/usr/bin/env python3
"""Stop the ladder from yielding to peers that are already stopped.

THE MEASUREMENT THAT FOUND THIS (tools/diag_paralysis.py, rush_50, fleet 24,
900 ticks, seed 11):

  config         done  YIELD  WAIT  moving%
  ladder_only      12   1568     0    92.6
  full              2   4919  4026    57.9

Enabling the safety kernel made the ladder issue 3.1x more YIELD verdicts. The
ladder cannot see the kernel, so the only channel between them is the radio, and
the only bit that crosses it is PeerView.holding.

THE FEEDBACK LOOP:

  1. The monitor vetoes robot A, so A's verdict is WAIT.
  2. _is_holding(A) reads that verdict from self._last_decisions, so on the next
     tick A broadcasts holding=True.
  3. B receives it. In _worst_encounter, `if failed or view.holding` sets
     following=False - correct in itself, a stopped robot is not a convoy.
  4. following=False sends B down the crossing branch to _contest(), and A, being
     stationary, has no momentum term, so B frequently loses and is issued YIELD.
  5. B is now holding too, and broadcasts it. The hold propagates outward one
     robot per tick.

The result is 17 of 24 robots held simultaneously and the moving fraction
collapsing from 92.6% to 57.9%.

THE DEFECT: yielding to a stationary robot accomplishes nothing. A yield is a
bargain - "you go first, I will wait" - and it only pays off if the other party
actually goes. Against a peer that is itself held, the yield buys nothing and
costs a tick, and because the yielding robot then declares itself holding, it
recruits its own neighbours into the same stall. This is a livelock built out of
individually correct decisions.

THE FIX: a holding peer is not a negotiation partner, it is an obstacle. Route
around it rather than bargaining with it:

  - do not enter _contest() against a holding peer, so no YIELD is issued and
    the hold cannot propagate;
  - SLOW while there is still room, which keeps the robot moving and is what the
    graded kernel is for;
  - once inside CONFLICT_M of a peer that is not going to move, REROUTE - the
    same rung _decide already uses for a CONFIRMED FAILED blocker, and for the
    identical reason, already stated in that branch: "Waiting behind a robot
    that is never going to move is a deadlock with extra steps, so the only
    correct rung is to go around."

A held peer is not permanently stuck the way a failed one is, so this is not
strictly the same situation - but the arbiter cannot tell the difference from one
tick of radio, and treating a hold as a soft obstacle is both safe and
self-correcting: if the peer starts moving again it stops advertising holding and
normal negotiation resumes immediately.

SAFETY: unaffected. This only changes which rung the LADDER proposes, and the
ladder is advisory - every proposal still passes through _monitor, which
enforces HARD_STOP_M and is the binding authority. The worst case is a REROUTE
where there used to be a YIELD, and both carry speed_scale 0.0 for the tick they
are issued, so no robot moves anywhere it could not have moved before.

Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "app" / "coordination" / "swarm_policy.py"

SENTINEL = "peer_holding"

# --- 1. carry the bit on the encounter -------------------------------------
ENC_OLD = """    peer_id: str
    distance: float
    following: bool
    peer_failed: bool = False
"""
ENC_NEW = """    peer_id: str
    distance: float
    following: bool
    peer_failed: bool = False
    # The peer declared itself held on its last tick. Such a peer is treated as
    # an obstacle to route around rather than as a party to negotiate with; see
    # tools/patch_no_yield_to_stationary.py for the measurement behind this.
    peer_holding: bool = False
"""

# --- 2. populate it -------------------------------------------------------
BUILD_OLD = """                worst = _Encounter(
                    peer_id=peer_id, distance=d, following=following,
                    peer_failed=failed,
                )
"""
BUILD_NEW = """                worst = _Encounter(
                    peer_id=peer_id, distance=d, following=following,
                    peer_failed=failed, peer_holding=bool(view.holding),
                )
"""

# --- 3. act on it, immediately before the crossing/contest branches -------
DECIDE_OLD = """        if enc.distance >= CONFLICT_M:
            # Close but not conflicting: both trim, neither stops. This rung is
            # the single biggest source of the throughput gap against
            # stop-and-wait, which would have halted one of them here.
            return Verdict(
                robot_id=rid, kind=VerdictKind.SLOW,
                reason=f"crossing {enc.peer_id} at {enc.distance:.2f} m",
                conflict_with=(enc.peer_id,),
            )

        return self._contest(rid, me, enc, inbox)
"""
DECIDE_NEW = """        if enc.peer_holding:
            # The peer is already stopped, so there is nothing to negotiate: a
            # yield is a bargain that only pays off if the other party moves,
            # and this one will not. Worse, yielding would make THIS robot
            # declare itself holding, which recruits its neighbours into the
            # same stall one tick at a time. That feedback loop cost 3.1x more
            # YIELD verdicts and dropped the moving fraction from 92.6% to
            # 57.9%; see tools/patch_no_yield_to_stationary.py.
            #
            # So treat the hold as an obstacle instead of a peer. Trim speed
            # while there is still room, and once genuinely blocked, go around -
            # exactly the reasoning the confirmed-failed branch above already
            # applies, because from one tick of radio the two situations are
            # indistinguishable.
            if enc.distance >= CONFLICT_M:
                return Verdict(
                    robot_id=rid, kind=VerdictKind.SLOW,
                    reason=(
                        f"{enc.peer_id} is holding at {enc.distance:.2f} m, "
                        f"easing past rather than yielding to a stopped peer"
                    ),
                    conflict_with=(enc.peer_id,),
                )
            self._yield_streak.pop(rid, None)
            self._counters.reroutes += 1
            return Verdict(
                robot_id=rid, kind=VerdictKind.REROUTE,
                reason=(
                    f"{enc.peer_id} is held and blocks the route at "
                    f"{enc.distance:.2f} m, replanning instead of waiting"
                ),
                conflict_with=(enc.peer_id,),
            )

        if enc.distance >= CONFLICT_M:
            # Close but not conflicting: both trim, neither stops. This rung is
            # the single biggest source of the throughput gap against
            # stop-and-wait, which would have halted one of them here.
            return Verdict(
                robot_id=rid, kind=VerdictKind.SLOW,
                reason=f"crossing {enc.peer_id} at {enc.distance:.2f} m",
                conflict_with=(enc.peer_id,),
            )

        return self._contest(rid, me, enc, inbox)
"""


def main() -> int:
    text = TARGET.read_text()

    if SENTINEL in text:
        print("no-yield-to-stationary patch already applied - nothing to do")
        return 0

    for name, old in (("encounter", ENC_OLD), ("build", BUILD_OLD), ("decide", DECIDE_OLD)):
        if old not in text:
            print(f"ERROR: {name} anchor not found, aborting", file=sys.stderr)
            return 1

    text = text.replace(ENC_OLD, ENC_NEW, 1)
    text = text.replace(BUILD_OLD, BUILD_NEW, 1)
    text = text.replace(DECIDE_OLD, DECIDE_NEW, 1)

    # The contest must remain reachable for peers that are actually moving,
    # otherwise the negotiation has been deleted rather than narrowed.
    if text.count("return self._contest(rid, me, enc, inbox)") != 1:
        print("ERROR: contest call no longer unique, aborting", file=sys.stderr)
        return 1

    TARGET.write_text(text)
    print("no-yield-to-stationary patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
