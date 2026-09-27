"""Engine side of X-10 / N9.

Three changes:

1. ROGUE_ROBOT now installs a real spoof offset, so the adversary lies rather
   than merely being labelled. The offset is drawn from the engine RNG, which
   keeps the run deterministic (N3).

2. A new `observations()` method: for each robot, the true positions of the
   peers it can physically see. This is the ground truth a witness compares a
   peer's CLAIM against, and it is the only place in the coordination path that
   is allowed to read true state - a detector that had to trust the claim in
   order to check the claim would be circular and useless.

3. `apply_containment()`: the engine records which robots the fleet has cut
   off, and a contained robot is stopped and stripped of its task so its work
   returns to the pool. Containment that left the robot driving would be a
   label, not a containment.
"""
import ast

ENG = "app/sim/engine.py"
src = open(ENG).read()

# ---- 1. rogue injection installs a real lie ---------------------------------
old = """    def _fault_rogue(self, robot_id: Optional[str] = None) -> dict:
        robot = self._pick_robot(robot_id)
        if robot is None:
            return {"applied": False, "reason": "no healthy robot"}
        robot.rogue = True
        return {"applied": True, "robot_id": robot.robot_id}
"""
new = """    def _fault_rogue(self, robot_id: Optional[str] = None,
                     spoof_m: float = 2.5) -> dict:
        \"\"\"Turn one robot into an adversary that lies about its position.

        The offset defaults to 2.5 m: well beyond the 1.5 m claim tolerance in
        app/coordination/integrity.py, so the lie is detectable, and beyond the
        0.70 m pair footprint, so it is genuinely dangerous - peers plan through
        the space the rogue actually occupies. A lie small enough to sit inside
        sensor noise would be neither.
        \"\"\"
        robot = self._pick_robot(robot_id)
        if robot is None:
            return {"applied": False, "reason": "no healthy robot"}
        robot.rogue = True
        # Direction from the engine RNG so the run stays reproducible; the
        # magnitude is fixed so the scenario is comparable across seeds.
        angle = self.rng.uniform(0.0, 2.0 * math.pi)
        robot.spoof_x = spoof_m * math.cos(angle)
        robot.spoof_y = spoof_m * math.sin(angle)
        return {"applied": True, "robot_id": robot.robot_id,
                "spoof_m": round(spoof_m, 2)}
"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- 2. observations() + 3. apply_containment(), after true_states ----------
old = """    # ==================================================================
    # step 1 - faults
    # =================================================================="""
new = '''    def observations(self, *, radius_m: float = 12.0) -> dict:
        """Per-robot ground-truth sightings of nearby peers.

        This stands in for onboard perception: a camera or lidar sees where a
        neighbour actually is, independently of what that neighbour says over
        the radio. Restricted to `radius_m` because a witness must not be able
        to testify about a robot on the far side of the warehouse - if it could,
        one honest robot would be enough to police the whole floor and the
        quorum requirement would be decoration.

        A robot outside the radius is simply ABSENT from the mapping, which the
        council reads as "cannot see", not as "is lying". Failed robots are
        still visible: a dead robot is a physical obstacle that peers can see
        perfectly well even though its radio has gone quiet.
        """
        out: dict[str, dict] = {}
        rids = sorted(self.robots)
        for rid in rids:
            me = self.robots[rid]
            seen: dict[str, tuple] = {}
            for other in rids:
                if other == rid:
                    continue
                peer = self.robots[other]
                if math.dist((me.x, me.y), (peer.x, peer.y)) <= radius_m:
                    seen[other] = (peer.x, peer.y)
            out[rid] = seen
        return out

    def apply_containment(self, robot_ids) -> list:
        """Record the fleet's containment decision and act on it.

        The decision itself is made in app/coordination/integrity.py by quorum;
        the engine only enforces it. A contained robot is halted and its task
        released back to the pool, because containment that left the robot
        driving and holding work would be a label rather than a containment.

        Releasing a robot restores it to AVAILABLE rather than to whatever it
        was doing, since its plan is by then long stale.
        """
        wanted = set(robot_ids)
        events: list[dict] = []
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            should = rid in wanted
            if should and not robot.quarantined:
                robot.quarantined = True
                robot.velocity = 0.0
                robot.speed_scale = 0.0
                released = robot.current_task_id
                if released is not None:
                    self._requeue_task(released)
                events.append({"robot_id": rid, "action": "quarantine",
                               "task_released": released})
            elif not should and robot.quarantined:
                robot.quarantined = False
                robot.speed_scale = 1.0
                if not robot.failed:
                    robot.status = RobotStatus.AVAILABLE
                events.append({"robot_id": rid, "action": "release",
                               "task_released": None})
        self._events_this_tick.extend(
            {"kind": "containment", **e} for e in events
        )
        return events

    # ==================================================================
    # step 1 - faults
    # =================================================================='''
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(ENG, "w").write(src)
print("engine.py patched OK")
