"""Stop a momentarily-held peer from being misclassified as crossing traffic.

THE LOOP BEING BROKEN. _worst_encounter computed

    if failed or view.holding:
        following = False

so any peer whose last verdict was a hold was excluded from the convoy rule and
fell through to _contest, which resolves it as crossing traffic and hands out a
YIELD at speed 0.

That bit is set by _is_holding via _HOLD_KINDS, which includes WAIT - and WAIT is
overwhelmingly what the SAFETY MONITOR issues, not the negotiation. So the
monitor and the ladder were coupled through the radio in a way neither was
designed for: one clamped leader poisoned the classification of every follower
behind it, each follower yielded to a full stop, each of those yields set its own
holding bit, and the stall propagated back down the aisle.

The measurement is unambiguous (rush_50, fleet 24, 900 ticks, seed 11):

    ladder_only (monitor off)   YIELD  1568   WAIT     0   moving 92.6%   12 done
    full        (monitor on)    YIELD  4919   WAIT  4026   moving 57.9%    2 done

Turning the monitor on tripled the ladder's YIELDs. The ladder has no channel to
the monitor other than this bit, so this bit is the coupling.

WHY EXCLUDING A HELD PEER WAS WRONG. `following` answers one question - are we
travelling the same way - and it is computed from headings. A peer that its
safety kernel clamped for a tick still has its path, still has its heading, and
will resume. It is not a robot that has given up its turn. Treating it as
crossing traffic is a misclassification of geometry, not a conservative choice.

AND IT IS NOT A SAFETY RELAXATION, which is the important half. Classifying the
pair as a convoy yields SLOW at 0.6, not PROCEED, so the follower still closes
only slowly; and the monitor is BINDING and runs afterwards on every verdict, so
if that reduced step would actually breach HARD_STOP_M it is clamped or held
regardless. The ladder is advisory with respect to separation - law 3 - so
softening a ladder rung cannot create a collision. What it removes is the
ladder's habit of pre-emptively stopping a robot the kernel would have allowed
through.

`failed` still suppresses the convoy rule, and must: a failed peer genuinely is
not going anywhere, has no meaningful heading, and the rung above this one
reroutes around it.

THE CONTEST IS UNTOUCHED. The rejected no-yield-to-stationary experiment lost
because it routed AROUND _contest and so lost the aging-based anti-starvation
guarantee. This patch changes only which branch a pair is classified into; every
pair that still reaches _contest is resolved by exactly the same rules.

PROCESS NOTE. The first version of this script emitted an `else:` whose body was
nothing but comments. The ast gate rejected it and NOTHING was written, which is
the safeguard patch_revert_no_yield.py lacked when it corrupted this file. The
commentary now goes inside the existing else block, which already has a body.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

OLD = """            if failed or view.holding:
                # Not going anywhere, so there is no shared direction of travel
                # and the convoy rule cannot apply.
                following = False
            else:
                their_dir = _heading_vector(peer)
"""

NEW = """            if failed:
                # A confirmed-failed peer has no meaningful heading and is never
                # going to move, so there is no shared direction of travel and
                # the convoy rule cannot apply. The rung above reroutes past it.
                following = False
            else:
                # NOTE view.holding is deliberately NOT consulted here. It used
                # to force following=False, which sent every follower behind a
                # momentarily-clamped leader into _contest to be resolved as
                # crossing traffic and stopped dead. Because _HOLD_KINDS
                # includes WAIT, and WAIT is mostly what the safety MONITOR
                # issues, that coupled the kernel back into the negotiation
                # through the radio: enabling the monitor tripled the ladder's
                # YIELDs (1568 -> 4919) and cut motion from 92.6% to 57.9% of
                # robot-ticks. A clamped peer still has its path and its heading
                # and will resume; it has not given up its turn.
                #
                # This is not a safety relaxation. The convoy branch grants SLOW
                # at 0.6, never PROCEED, and the monitor is binding and runs
                # after every verdict, so a step that would truly breach
                # HARD_STOP_M is still clamped or held. The ladder is advisory
                # on separation, so softening a rung here cannot create a
                # collision - it only stops the ladder from pre-emptively
                # halting a robot the kernel would have let through.
                their_dir = _heading_vector(peer)
"""


def main() -> int:
    src = open(PATH).read()

    if "view.holding is deliberately NOT consulted" in src:
        print("already applied")
        return 0

    n = src.count(OLD)
    if n != 1:
        print(f"ABORT: anchor matched {n} times, expected exactly 1")
        return 1

    fixed = src.replace(OLD, NEW, 1)

    # The gate. Nothing is written unless the result is valid Python.
    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: result does not parse: {exc}")
        return 1

    # The contest must still be reachable and the kernel must still be binding.
    if "return self._contest(rid, me, enc, inbox)" not in fixed:
        print("ABORT: contest tail call lost")
        return 1
    if "HARD_STOP_M" not in fixed:
        print("ABORT: safety floor vanished")
        return 1
    if fixed.count("following = ") < 2:
        print("ABORT: following no longer assigned on every path")
        return 1
    # A failed peer must still be excluded from the convoy rule.
    if "if failed:\n" not in fixed:
        print("ABORT: failed-peer guard lost")
        return 1

    open(PATH, "w").write(fixed)
    print("applied: held peer no longer misclassified as crossing traffic")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
