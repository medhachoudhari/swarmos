"""Fix apply_containment to use the real task-release helper.

I wrote `self._requeue_task(released)`, which does not exist - the engine's
helper is `_release_task(robot, reason=...)` and it takes the robot, does the
full teardown (path, phase, goal cell, dwell, carrying mass) and emits its own
task_released event. Calling a name that does not exist would have raised
AttributeError the first time a quorum was ever reached, which is exactly the
path least likely to be exercised by accident.
"""
import ast

ENG = "app/sim/engine.py"
src = open(ENG).read()

old = """                released = robot.current_task_id
                if released is not None:
                    self._requeue_task(released)
                events.append({"robot_id": rid, "action": "quarantine",
                               "task_released": released})"""
new = """                released = robot.current_task_id
                if released is not None:
                    # _release_task does the whole teardown - path, phase, goal
                    # cell, dwell, carried mass - and emits its own event. Only
                    # clearing current_task_id would leave a task assigned to a
                    # robot that will never move it, which is a slow leak of
                    # fleet capacity rather than a containment.
                    self._release_task(robot, reason="quarantined")
                events.append({"robot_id": rid, "action": "quarantine",
                               "task_released": released})"""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(ENG, "w").write(src)
print("containment fix OK")
