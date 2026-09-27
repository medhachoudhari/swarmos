"""X-01 step 4: COMM_BLACKOUT fault, sovereign mirror and KPI in M5.

DESIGN NOTES worth keeping

  The blackout is a FAULT, not a policy setting, so it goes through the same
  inject() table as every other fault and is therefore scriptable from a
  scenario and clickable from the Lab panel with no second mechanism.

  It auto-restores after `ticks`, because a blackout nobody lifts proves only
  half the claim. The claim is "keeps working alone, THEN rejoins cleanly", and
  the rejoin is the harder half. The pending-restore map is keyed by robot id and
  checked once per tick, in sorted id order, so the restore point is
  deterministic and the run stays replayable (N3).

  SimRobot.sovereign is a MIRROR, written from the policy and read by the wire
  form. The direction matters: the simulation is the single authority on robot
  state (law 1), so the engine READS the policy's judgement and records it,
  exactly as it already does for containment. Unlike quarantine, sovereign mode
  does NOT stop the robot and does NOT release its task - that is the entire
  point of the feature, and a mirror that behaved like quarantine would quietly
  refute the claim it exists to demonstrate.
"""
import ast
import pathlib

def sub(t, old, new, label):
    assert t.count(old) == 1, f"{label}: expected 1 match, got {t.count(old)}"
    return t.replace(old, new)


# ---------------------------------------------------------------- scenarios
S = pathlib.Path("app/sim/scenarios.py")
s = S.read_text()
if "COMM_BLACKOUT" in s:
    print("scenarios.py already has COMM_BLACKOUT, skipping")
else:
  s = sub(
    s,
    '    KILL_ML = "KILL_ML"',
    '''    KILL_ML = "KILL_ML"
    # X-01. Cuts one robot's radio in both directions. Proves that a robot which
    # can no longer coordinate keeps working under a tighter envelope instead of
    # stopping and blocking an aisle, and rejoins the moment it is audible again.
    COMM_BLACKOUT = "COMM_BLACKOUT"''',
    "faultkind",
)
ast.parse(s)
S.write_text(s)
print("scenarios.py OK")

# ------------------------------------------------------------------- robot
R = pathlib.Path("app/sim/robot.py")
r = R.read_text()
r = sub(
    r,
    "    quarantined: bool = False",
    """    quarantined: bool = False
    # X-01 mirror of the arbiter's sovereign set. Display and reporting only:
    # unlike quarantined it does NOT stop the robot and does NOT release its
    # task, because continuing to work is precisely what is being demonstrated.
    sovereign: bool = False""",
    "robot flag",
)
r = sub(
    r,
    '''            # QUARANTINED overrides the lifecycle status for display only.
            # The operator needs to see at a glance which robots the fleet has
            # cut off, and that is not expressible as a hardware state.
            "s": ("QUARANTINED" if self.quarantined else self.status.value),''',
    '''            # QUARANTINED and SOVEREIGN override the lifecycle status for
            # display only, and QUARANTINED outranks SOVEREIGN: a contained liar
            # is the more urgent fact about a robot than a lost radio, and an
            # operator shown only "SOVEREIGN" for a quarantined rogue would be
            # actively misled.
            "s": (
                "QUARANTINED" if self.quarantined
                else "SOVEREIGN" if self.sovereign
                else self.status.value
            ),''',
    "robot wire",
)
ast.parse(r)
R.write_text(r)
print("robot.py OK")

# ------------------------------------------------------------------ engine
E = pathlib.Path("app/sim/engine.py")
e = E.read_text()

e = sub(
    e,
    "            FaultKind.KILL_ML: self._fault_kill_ml,",
    """            FaultKind.KILL_ML: self._fault_kill_ml,
            FaultKind.COMM_BLACKOUT: self._fault_comm_blackout,""",
    "fault table",
)

e = sub(
    e,
    """    def _fault_kill_ml(self) -> dict:
        self.ml_enabled = False
        return {"applied": True, "ml_enabled": False}""",
    '''    def _fault_kill_ml(self) -> dict:
        self.ml_enabled = False
        return {"applied": True, "ml_enabled": False}

    def _fault_comm_blackout(self, robot_id: Optional[str] = None,
                             ticks: int = 60) -> dict:
        """Cut one robot's radio for `ticks` ticks, then restore it (X-01).

        60 ticks is 6 s at 10 Hz: long enough to clear the 5-tick confirmation
        window with room to spare and to be visible to a human watching the map,
        short enough that a judge sees the rejoin inside the same demo breath.

        getattr rather than attribute access because the baseline policy has no
        radio at all, and forcing one on it to satisfy this fault would corrupt
        the comparison the whole throughput claim rests on.
        """
        radio = getattr(self.policy, "radio", None)
        if radio is None:
            return {"applied": False, "reason": "policy has no radio"}
        robot = self._pick_robot(robot_id)
        if robot is None:
            return {"applied": False, "reason": "no healthy robot"}
        radio.silence(robot.robot_id)
        self._blackout_until[robot.robot_id] = self.clock.tick + max(1, int(ticks))
        return {"applied": True, "robot_id": robot.robot_id,
                "ticks": max(1, int(ticks))}

    def _expire_blackouts(self) -> None:
        """Restore radios whose blackout has run out (X-01).

        Sorted id order so the restore sequence is identical on every replay.
        """
        if not self._blackout_until:
            return
        radio = getattr(self.policy, "radio", None)
        if radio is None:
            self._blackout_until.clear()
            return
        for rid in sorted(self._blackout_until):
            if self.clock.tick >= self._blackout_until[rid]:
                radio.restore(rid)
                del self._blackout_until[rid]
                self._emit("blackout_ended", robot_id=rid)

    def _sync_sovereign(self) -> None:
        """Copy the arbiter's sovereign set onto the robots (X-01).

        Read back from the policy, never pushed by it, for the same reason
        apply_containment is: the simulation stays the single authority on robot
        state (law 1). Deliberately does NOT touch velocity, speed_scale, status
        or the current task - a sovereign robot is still working.
        """
        ids = getattr(self.policy, "sovereign", None)
        if ids is None:
            return
        wanted = set(ids)
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            should = rid in wanted
            if should and not robot.sovereign:
                robot.sovereign = True
                self._emit("sovereign", robot_id=rid, action="enter")
            elif not should and robot.sovereign:
                robot.sovereign = False
                self._emit("sovereign", robot_id=rid, action="rejoin")''',
    "handlers",
)

e = sub(
    e,
    """        council = getattr(self.policy, "council", None)
        if council is not None:
            self.apply_containment(council.contained)
""",
    """        council = getattr(self.policy, "council", None)
        if council is not None:
            self.apply_containment(council.contained)
        # X-01. Same read-back discipline as containment, and for the same
        # reason: coordination judges, the simulation records.
        self._sync_sovereign()
        self._expire_blackouts()
""",
    "step wiring",
)

e = sub(
    e,
    '''            "robots_rogue": sum(1 for r in self.robots.values() if r.rogue),''',
    '''            "robots_rogue": sum(1 for r in self.robots.values() if r.rogue),
            # X-01. Beside robots_rogue and not folded into it: a robot with a
            # dead radio and a robot telling lies are different problems with
            # different operator responses.
            "robots_sovereign": sum(
                1 for r in self.robots.values() if r.sovereign
            ),''',
    "kpi",
)

e = sub(
    e,
    "        self.policy = policy",
    """        self.policy = policy
        # X-01. tick at which each silenced robot's radio comes back. Engine
        # state rather than radio state, because the radio's job is to model
        # reachability, not to schedule the operator's faults.
        self._blackout_until: dict[str, int] = {}""",
    "engine state",
)

ast.parse(e)
E.write_text(e)
print("engine.py OK")
