"""Reserve the full-stop contest for the safety floor instead of 0.22 m above it.

THE REDUNDANCY. Three thresholds were in play and two of them did the same job:

    StopAndWaitPolicy stops when swept segments close within 0.75 m
                                          (SAFE_SEPARATION_M)
    SwarmPolicy._monitor holds/clamps below 0.75 m   (HARD_STOP_M), and is
                                          BINDING - it runs on every verdict
    SwarmPolicy._decide  sent the pair to _contest below 0.97 m (CONFLICT_M),
                                          and _contest hands the loser YIELD,
                                          i.e. speed 0

So the negotiation was issuing FULL STOPS 0.22 m before the floor that the kernel
already guarantees. For the whole band 0.75 to 0.97 m the ladder stopped a robot
that the monitor would have allowed through - and if the motion had genuinely
been unsafe, the monitor would have caught it, because it is binding and runs
afterwards. That band is a second, stricter, redundant safety rule living inside
the component that is explicitly NOT the safety authority.

It is also the dominant verdict: `full` issues 3360 to 5541 YIELDs per run, all
of them speed 0, while `ladder_only` at 92% motion completes +94.7%.

THE CHANGE. The crossing path becomes graded all the way down to the floor:

    distance >= CONFLICT_M (0.97)          SLOW at the default 0.4  (unchanged)
    HARD_STOP_M <= distance < CONFLICT_M   SLOW at CLOSING_SCALE    (new rung)
    distance < HARD_STOP_M (0.75)          _contest, as before

Each robot keeps closing slowly through the new band, and the monitor decides
what that actually means in metres. Only at the floor - where someone really must
give way - does the ladder spend a full stop and pick a winner.

WHY THIS IS SAFE. The monitor is binding (law 2) and the ladder is advisory on
separation, so a ladder rung cannot create a collision on its own: whatever SLOW
this rung asks for is re-tested against HARD_STOP_M and clamped or held. The
floor is untouched, the geometry is untouched, and the kernel's time-agnostic
segment test is untouched. This patch only stops the ladder from pre-empting a
decision that belongs to the kernel.

WHY THE CONTEST SURVIVES - which is the trap the rejected no-yield-to-stationary
patch fell into. _contest is still the only resolution below the floor, and a
crossing pair converging in an aisle still reaches it, because the monitor holds
them near 0.75 m and the next tick they are inside it. So the aging term, the
yield streaks, COMMIT_TICKS and the anti-starvation guarantee all still apply to
exactly the encounters they were built for. Nothing routes around _contest; the
band above the floor is merely no longer treated AS the floor.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

# Sits next to the other tunables so the RULE 1 / RULE 2 ordering stays visible.
CONST_ANCHOR = "YIELD_PATIENCE = 10\n"

CONST_NEW = """YIELD_PATIENCE = 10
# Speed granted while crossing traffic is inside CONFLICT_M but still outside the
# monitor's HARD_STOP_M floor. The ladder used to spend a full-stop YIELD on this
# entire band, 0.22 m before the floor the binding kernel already enforces, which
# made it the dominant verdict in the fleet (3360-5541 per run). Closing slowly
# instead leaves the decision about metres to the component that owns it.
CLOSING_SCALE = 0.25
"""

OLD = """        if enc.distance >= CONFLICT_M:
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

NEW = """        if enc.distance >= CONFLICT_M:
            # Close but not conflicting: both trim, neither stops. This rung is
            # the single biggest source of the throughput gap against
            # stop-and-wait, which would have halted one of them here.
            return Verdict(
                robot_id=rid, kind=VerdictKind.SLOW,
                reason=f"crossing {enc.peer_id} at {enc.distance:.2f} m",
                conflict_with=(enc.peer_id,),
            )

        if enc.distance >= HARD_STOP_M:
            # Inside the conflict band but still outside the monitor's floor.
            # This used to go straight to _contest, which stops the loser dead -
            # a full stop 0.22 m before the floor the BINDING kernel already
            # enforces, duplicating the safety rule inside the component that is
            # explicitly not the safety authority. Closing slowly is enough: the
            # monitor re-tests this step against HARD_STOP_M and clamps or holds
            # it if the geometry really demands it, so the decision about metres
            # stays with the kernel while the negotiation keeps the aisle moving.
            return Verdict(
                robot_id=rid, kind=VerdictKind.SLOW,
                reason=(
                    f"closing on {enc.peer_id} at {enc.distance:.2f} m, easing "
                    f"toward the {HARD_STOP_M:.2f} m floor"
                ),
                speed_scale=CLOSING_SCALE,
                conflict_with=(enc.peer_id,),
            )

        # At or inside the floor, so somebody genuinely has to give way and it is
        # worth spending a full stop to decide who. The contest is still the ONLY
        # resolution here, which is what keeps the aging term, the yield streaks
        # and the anti-starvation guarantee attached to the encounters they were
        # designed for. A converging pair still arrives: the monitor holds them
        # near the floor and the next tick they are inside it.
        return self._contest(rid, me, enc, inbox)
"""


def main() -> int:
    src = open(PATH).read()

    if "CLOSING_SCALE" in src:
        print("already applied")
        return 0

    for name, text in (("constant", CONST_ANCHOR), ("ladder", OLD)):
        n = src.count(text)
        if n != 1:
            print(f"ABORT: {name} anchor matched {n} times, expected 1")
            return 1

    fixed = src.replace(CONST_ANCHOR, CONST_NEW, 1).replace(OLD, NEW, 1)

    # The gate. Nothing is written unless the result is valid Python.
    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: result does not parse: {exc}")
        return 1

    # Invariants that must survive any change to the ladder.
    if fixed.count("return self._contest(rid, me, enc, inbox)") != 1:
        print("ABORT: contest must remain reachable exactly once")
        return 1
    if "HARD_STOP_M" not in fixed:
        print("ABORT: safety floor vanished")
        return 1
    # The new rung must sit BELOW the conflict band and ABOVE the floor, so the
    # ordering CONFLICT_M > HARD_STOP_M must still hold (RULE 2).
    if "CONFLICT_M = HARD_STOP_M + MAX_STEP_M" not in fixed:
        print("ABORT: CONFLICT_M no longer derived from the floor")
        return 1
    if "if enc.distance >= HARD_STOP_M:" not in fixed:
        print("ABORT: new closing rung missing")
        return 1

    open(PATH, "w").write(fixed)
    print("applied: contest reserved for the floor, closing band now graded")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
