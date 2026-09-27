"""Give containment teeth.

Three defects exposed by tests/test_integrity.py, all mine:

1. apply_containment appended straight to _events_this_tick, bypassing
   _emit(), so the containment never reached self.events - the feed the UI
   and the operator actually read. A containment nobody can see in the feed
   is the silent mechanism this project rejects everywhere else.
2. _dispatch gates on is_available_for_work, which knew nothing about
   quarantine, so a contained robot was handed fresh work on the next tick.
3. _plan regenerated a path for a contained robot, so it drove again.

Together these made containment a label that lasted exactly one tick.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def patch(rel, pairs):
    path = ROOT / rel
    src = path.read_text()
    for old, new in pairs:
        assert src.count(old) == 1, (rel, old[:60], src.count(old))
        src = src.replace(old, new)
    ast.parse(src)
    path.write_text(src)
    print("patched", rel)


# -- 1. containment events must reach self.events -------------------------
patch("app/sim/engine.py", [(
    """        self._events_this_tick.extend(
            {"kind": "containment", **e} for e in events
        )
        return events""",
    """        for event in events:
            # _emit, not a direct append: the operator's event feed reads
            # self.events, and a containment that does not appear there is
            # invisible to the very person who has to judge it.
            self._emit("containment", **event)
        return events""",
), (
    # -- 3. no replanning for a contained robot
    """            if robot.failed or robot.status is RobotStatus.CHARGING:
                continue
            if self._dwell.get(rid, 0) > 0:
                continue""",
    """            if robot.failed or robot.status is RobotStatus.CHARGING:
                continue
            if robot.quarantined:
                # A contained robot gets no new path. Planning for it would
                # hand back the motion the containment just took away.
                continue
            if self._dwell.get(rid, 0) > 0:
                continue""",
)])

# -- 2. a contained robot is not eligible for work ------------------------
patch("app/sim/robot.py", [(
    """        if self.failed:
            return False
        if self.status in (RobotStatus.FAILED, RobotStatus.CHARGING):
            return False""",
    """        if self.failed:
            return False
        if self.quarantined:
            # Containment is a fleet decision, but eligibility is decided
            # here, so it has to be honoured here too - otherwise the
            # dispatcher quietly undoes it one tick later.
            return False
        if self.status in (RobotStatus.FAILED, RobotStatus.CHARGING):
            return False""",
)])
