"""Repair the _decide ladder in app/coordination/swarm_policy.py.

tools/patch_revert_no_yield.py used an 8-space end anchor
"        if enc.distance >= CONFLICT_M:" which also occurs as a SUFFIX of the
12-space nested line inside the block it was deleting. str.index matched at
offset 4 of that nested line, so the cut ended mid-block and left an orphaned
body with an IndentationError at the following statement.

This script deletes the orphaned remains. The region is identified by its own
unique text (the "easing past rather than yielding" reason string, which only
the rejected no-yield-to-stationary experiment ever produced) and the cut ends
at the surviving good crossing rung, matched on its comment line so no suffix
collision is possible.

Lesson enforced here: the script parses the result with ast before writing.
Text validators alone let the previous corruption through.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

# Unique to the damaged region: the mis-indented "return Verdict(" that the
# bad cut left attached to an 8-space "if".
START = (
    "        if enc.distance >= CONFLICT_M:\n"
    "                return Verdict(\n"
)

# The surviving good rung. Anchored on the comment so the match cannot be a
# suffix of any deeper-indented line.
END = (
    "        if enc.distance >= CONFLICT_M:\n"
    "            # Close but not conflicting: both trim, neither stops."
)


def main() -> int:
    src = open(PATH).read()

    if START not in src:
        try:
            ast.parse(src)
        except SyntaxError as exc:
            print(f"ABORT: damage marker absent but file still broken: {exc}")
            return 1
        print("already repaired (marker absent, file parses)")
        return 0

    a = src.index(START)
    b = src.index(END)
    if b <= a:
        print("ABORT: end anchor precedes start anchor")
        return 1

    fixed = src[:a] + src[b:]

    # Syntax is the gate. Nothing is written until the result parses.
    try:
        ast.parse(fixed)
    except SyntaxError as exc:
        print(f"ABORT: repaired text does not parse: {exc}")
        return 1

    # The ladder must still end in a contest. Routing around _contest is what
    # cost the anti-starvation guarantee last time.
    if fixed.count("return self._contest(rid, me, enc, inbox)") != 1:
        print("ABORT: expected exactly one _contest tail call")
        return 1
    if "easing past rather than yielding" in fixed:
        print("ABORT: rejected no-yield-to-stationary text survives")
        return 1

    open(PATH, "w").write(fixed)
    print(f"repaired _decide, removed {b - a} characters")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
