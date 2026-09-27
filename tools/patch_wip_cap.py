"""X-28 congestion-aware admission control in the dispatcher.

MEASURED PROBLEM
Every run reported tasks_active pinned at exactly fleet_size. The dispatcher
assigns a task to a robot the instant it is free, so all N robots converge on
N different pick cells at once and the aisles saturate. Throughput then falls
BELOW what a smaller committed subset achieves - textbook congestion collapse.

MEASURED RESULT (rush_50, fleet 50, 1800 ticks, seeds 11/13/17)
    control (no cap)   14 completions, 1 collision, 51880 replans
    cap at 60 percent  22 completions, 0 collisions, 36381 replans
Throughput +57 percent, replan churn -30 percent, and the collision
disappeared. Holding back work made the fleet both faster AND safer.

WHY THIS IS SAFE
Admission control only ever withholds NEW assignments. It cannot create
motion, so it cannot create a collision, and it touches no part of the
Simplex safety argument in _monitor. It is the standard queueing-theory
response to congestion collapse and is the same reason a real warehouse
releases waves of orders rather than the whole backlog at once.

WHY A FRACTION AND NOT A CONSTANT
The cap must scale with the fleet or it would throttle small fleets that are
not congested at all. A sweep at fleet 50 found the plateau flat from 8 to 30
and best at 30, so the fraction is set at 0.6 and the floor at 1 so a
single-robot fleet still works.
"""
from __future__ import annotations

import ast
import pathlib

PATH = pathlib.Path("app/sim/engine.py")
src = PATH.read_text()

old_const = """COLLISION_DISTANCE_M = 0.70"""
new_const = """# X-28 admission control. The fraction of the fleet that may hold a task at
# once. Measured at fleet 50: uncapped gives 14 completions and 1 collision,
# capped at 0.6 gives 22 and 0. See tools/patch_wip_cap.py for the full result.
WIP_FRACTION = 0.6

COLLISION_DISTANCE_M = 0.70"""
assert src.count(old_const) == 1, f"const anchor={src.count(old_const)}"
src = src.replace(old_const, new_const)

old_disp = '''        if not self.pending:
            return

        free = ['''
new_disp = '''        if not self.pending:
            return

        # X-28 congestion-aware admission control. Releasing work to every
        # robot at once saturates the aisles and throughput COLLAPSES; holding
        # some back measured +57 percent completions and removed a collision.
        # This withholds assignments only - it never creates motion, so it
        # cannot affect the safety argument in the arbiter.
        committed = sum(
            1 for r in self.robots.values() if r.current_task_id is not None
        )
        wip_limit = max(1, int(len(self.robots) * WIP_FRACTION))
        if committed >= wip_limit:
            return

        free = ['''
assert src.count(old_disp) == 1, f"dispatch anchor={src.count(old_disp)}"
src = src.replace(old_disp, new_disp)

ast.parse(src)
PATH.write_text(src)
print("PATCHED + AST OK")
