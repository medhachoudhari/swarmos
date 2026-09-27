"""Revert tools/patch_contest_at_floor.py. MEASURED AND REJECTED.

The hypothesis was that the ladder's full-stop YIELD anywhere below CONFLICT_M
(0.97 m) was redundant with the binding monitor's HARD_STOP_M floor (0.75 m), so
the 0.75-0.97 m band should be graded (SLOW at CLOSING_SCADLE) and _contest
reserved for the floor itself.

    config          completions        collisions
    baseline        19 (unchanged)     0 / 0 / 0
    ladder_only     37 -> 33  (+73.7%) 70 / 58 / 43
    full            13 -> 11  (-42.1%) 0 / 0 / 0

It lost on BOTH configs, including ladder_only where the monitor is switched off
entirely and the change is therefore purely a negotiation effect. That rules out
any interaction with the kernel and points at the ladder itself.

WHY IT LOST - and this is the no-yield-to-stationary lesson arriving from the
opposite direction, which is what makes it worth trusting now.

Creeping slowly toward a peer does not resolve an encounter, it POSTPONES it into
a worse position. Yielding at 0.97 m ends the encounter: one robot stops, the
other passes, the aisle clears, and the yielder resumes with its aging term
raised so it wins the next contest. Closing to 0.75 m at CLOSING_SCALE instead
delivers both robots INTO the floor band still moving and still unresolved, where
the monitor now has two robots to hold rather than one, and _contest is entered
from a geometry with no room left to manoeuvre. The band was not redundant
safety - it was the space in which the negotiation had room to work.

So the earlier finding generalises, and it is now observed twice from opposite
edits:

> A YIELD is not wasted motion, it is the mechanism by which a wedge RESOLVES.
> Removing yields (patch_no_yield_to_stationary: ladder_only 37 -> 17) and
> delaying them (this patch: ladder_only 37 -> 33) both lose. The contest needs
> to happen EARLY and at speed zero, with room still in hand.

Which also explains why `full` cannot simply be made more permissive: its deficit
is not that it stops too often, it is that its stops are imposed by the kernel on
geometry the negotiation never got to resolve. The remaining lead is therefore
still the one in section 2 of SESSION_SUMMARY_20260921_0050: make the KERNEL less
pessimistic, time-agnostically, so fewer encounters reach it unresolved. Making
the LADDER later or softer is now measured as counter-productive twice over.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

CONST_NEW = """YIELD_PATIENCE = 10
# Speed granted while crossing traffic is inside CONFLICT_M but still outside the
# monitor's HARD_STOP_M floor. The ladder used to spend a full-stop YIELD on this
# entire band, 0.22 m before the floor the binding kernel already enforces, which
# made it the dominant verdict in the fleet (3360-5541 per run). Closing slowly
# instead leaves the decision about metres to the component that owns it.
CLOSING_SCALE = 0.25
"""

CONST_OLD = "YIELD_PATIENCE = 10\n"

NEW_BLOCK_START = "        if enc.distance >= HARD_STOP_M:\n"
CONTEST_TAIL = "        return self._contest(rid, me, enc, inbox)\n"

ORIGINAL_TAIL = """        # Below CONFLICT_M somebody has to give way, and it is worth spending a
        # full stop to decide who. Grading this band instead - closing slowly
        # toward the floor rather than yielding here - was measured and REJECTED:
        # ladder_only fell 37 -> 33 and full fell 13 -> 11. Creeping does not
        # resolve an encounter, it postpones it into a geometry with no room
        # left, delivering BOTH robots into the floor band still unresolved. The
        # band above the floor is not redundant safety, it is the space the
        # negotiation needs in order to work. See
        # tools/patch_revert_contest_at_floor.py.
        return self._contest(rid, me, enc, inbox)
"""


def main() -> int:
    src = open(PATH).read()

    if "CLOSING_SCALE" not in src:
        try:
            ast.parse(src)
        except SyntaxError as exc:
            print(f"ABORT: marker absent but file broken: {exc}")
            return 1
        print("already reverted")
        return 0

    # Drop the constant.
    if CONST_NEW not in src:
        print("ABORT: constant block not found verbatim")
        return 1
    fixed = src.replace(CONST_NEW, CONST_OLD, 1)

    # Excise the new rung: from its `if` up to and including the contest tail.
    a = fixed.find(NEW_BLOCK_START)
    if a < 0:
        print("ABORT: closing rung not found")
        return 1
    b = fixed.find(CONTEST_TAIL, a)
    if b < 0:
        print("ABORT: contest tail not found after the closing rung")
        return 1
    fixed = fixed[:a] + ORIGINAL_TAIL + fixed[b + len(CONTEST_TAIL):]

    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: reverted text does not parse: {exc}")
        return 1

    if "CLOSING_SCALE" in fixed:
        print("ABORT: rejected constant survives")
        return 1
    if fixed.count("return self._contest(rid, me, enc, inbox)") != 1:
        print("ABORT: contest must be reachable exactly once")
        return 1
    if "HARD_STOP_M" not in fixed:
        print("ABORT: safety floor vanished")
        return 1

    open(PATH, "w").write(fixed)
    print("reverted: contest restored for the whole sub-CONFLICT_M band")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
