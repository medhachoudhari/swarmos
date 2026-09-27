"""Experiment A: unwind stall cascades from the FRONT by resolving in priority order.

Motivation, from tools/diag_veto_cause.py over 13299 vetoes: 59.4% held_peer,
40.2% already_inside, 0.5% moving_peer. 99.5% of kernel vetoes are provoked by a
peer that has ALREADY STOPPED. That is a stall cascade - A holds, B holds because
A occupies the aisle, C holds behind B - and it is a queue phenomenon, not a
geometry one.

A queue can only drain from its head. But arbitrate() currently resolves robots in
ascending robot-id order, which bears no relation to queue position, so on any
given tick the arbiter may decide a robot at the BACK of a jam before the robot at
the front that is actually free to move. The one at the back is then judged against
a front robot still recorded as stationary, gets vetoed, and the jam persists for
another tick even though it was geometrically resolvable.

Resolving nearest-to-goal first gives the fleet a consistent unwinding direction.
The robot with the least remaining path is the most likely to be leaving the
congested region entirely, so deciding it first publishes real motion into
`granted` before anyone behind it is judged.

Why this does NOT violate either standing rule:
  1. It never assumes a peer will VACATE space. Every peer not yet decided is
     still treated as a stationary point exactly as before, which is the
     conservative assumption. Only the ORDER of decisions changes; the floor test
     itself is untouched.
  2. It does not bypass _contest. The negotiation ladder and the kernel both run
     unchanged for every robot.

It also remains fully deterministic: the sort key is (remaining_path, robot_id),
so ties break on id and the same inputs give the same order every run. This is a
prerequisite for the N3 replay claim and is covered by the existing tests.

Gated behind PRIORITY_ORDER so the A/B can be measured both ways in one process.
"""
import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "app" / "coordination" / "swarm_policy.py"

FLAG_ANCHOR = "MONITOR_STUCK_TICKS = 4"

FLAG_BLOCK = '''MONITOR_STUCK_TICKS = 4

# Resolve robots nearest-to-goal first rather than in robot-id order, so a stall
# cascade unwinds from its head. See tools/patch_priority_order.py for the full
# argument; in short, 99.5% of kernel vetoes are caused by already-stopped peers,
# a queue only drains from the front, and id order has no relation to queue
# position. Only the decision ORDER changes - the floor test and the negotiation
# ladder are untouched, and every undecided peer is still treated as a stationary
# point, so the kernel remains as conservative as before.
PRIORITY_ORDER = True'''

ORDER_OLD = """        self._counters.ticks += 1
        self._tick = tick
        ids = sorted(states)"""

ORDER_NEW = """        self._counters.ticks += 1
        self._tick = tick
        if PRIORITY_ORDER:
            # Nearest-to-goal first, ties broken on id so the order is total and
            # reproducible. A robot about to leave the congested region publishes
            # real motion into `granted` before anyone queued behind it is judged.
            ids = sorted(states, key=lambda r: (_remaining_path_m(states[r]), r))
        else:
            ids = sorted(states)"""


def main() -> int:
    text = SRC.read_text()
    if "PRIORITY_ORDER" in text:
        print("already applied")
        return 0
    if FLAG_ANCHOR not in text or ORDER_OLD not in text:
        print("ERROR: anchor not found", file=sys.stderr)
        return 1
    out = text.replace(FLAG_ANCHOR, FLAG_BLOCK, 1)
    out = out.replace(ORDER_OLD, ORDER_NEW, 1)
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print(f"ERROR: does not parse ({exc})", file=sys.stderr)
        return 1
    SRC.write_text(out)
    print("applied: PRIORITY_ORDER gate added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
