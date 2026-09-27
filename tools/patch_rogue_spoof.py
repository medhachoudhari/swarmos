"""Make the ROGUE_ROBOT fault actually lie, instead of only carrying a flag.

Before this patch `SimRobot.rogue` was a boolean nobody consumed: the fault
injection set it and the adversary then behaved exactly like an honest robot.
A containment mechanism tested against an adversary that does not misbehave
proves nothing, so the flag is given teeth here - a rogue robot broadcasts a
position offset from where it really is, which is the single most damaging lie
available to it (it makes peers plan through the space it actually occupies).

The UI keeps showing the TRUE position, with the claim carried separately as
"cl", so an operator watching the map sees the divergence rather than being
deceived along with the fleet.
"""
import ast

ROBOT = "app/sim/robot.py"
src = open(ROBOT).read()

old = """    # Set true by a fault injection. A rogue robot inflates its bids; the
    # simulation only carries the flag, detection lives in M4 (X-10).
    rogue: bool = False
"""
new = """    # Set true by a fault injection. A rogue robot broadcasts a position it is
    # not at; see spoof_x/spoof_y. Detection and containment live in M4
    # (app/coordination/integrity.py, X-10 / N9).
    rogue: bool = False

    # Metres of deliberate falsification added to the BROADCAST position when
    # rogue is set. This is the lie itself, not sensor error: it is applied to
    # what peers are told and never to where the robot really is, so the
    # simulation's own physics and the collision scorer remain truthful.
    spoof_x: float = 0.0
    spoof_y: float = 0.0

    # Set by the coordination layer when a quorum of peers has contained this
    # robot. Deliberately NOT a RobotStatus value: quarantine is a statement
    # the fleet makes about a robot, not a state of the robot's own hardware,
    # and collapsing the two would corrupt the canonical lifecycle model.
    quarantined: bool = False
"""
assert src.count(old) == 1
src = src.replace(old, new)

# to_amr_state: the broadcast view carries the lie
old = """        if reported:
            px, py = self.reported_x, self.reported_y
        else:
            px, py = self.x, self.y
"""
new = """        if reported:
            # The broadcast view. For an honest robot this is true position
            # plus sensor error; for a rogue robot the deliberate offset is
            # added here, because this is the only place the outside world
            # reads a position from, and so the only place a lie can live.
            px, py = self.claimed_x, self.claimed_y
        else:
            px, py = self.x, self.y
"""
assert src.count(old) == 1
src = src.replace(old, new)

# claimed_* accessors, inserted just before _update_reported
old = """    def _update_reported(
        self, moved_m: float, rng: random.Random, sensing: SensingProfile
    ) -> None:"""
new = """    @property
    def claimed_x(self) -> float:
        \"\"\"The x this robot tells its peers it is at.

        Equal to reported_x for every honest robot. The spoof offset is kept
        separate from drift and jitter on purpose: sensor error is something
        that happens TO a robot and is bounded by the sensing profile, whereas
        this is something the robot does, and the two must never be summed into
        one unexplainable number.
        \"\"\"
        return self.reported_x + (self.spoof_x if self.rogue else 0.0)

    @property
    def claimed_y(self) -> float:
        return self.reported_y + (self.spoof_y if self.rogue else 0.0)

    def _update_reported(
        self, moved_m: float, rng: random.Random, sensing: SensingProfile
    ) -> None:"""
assert src.count(old) == 1
src = src.replace(old, new)

# render dict: truth for the operator, claim alongside it
old = """            "s": self.status.value,"""
new = """            # QUARANTINED overrides the lifecycle status for display only.
            # The operator needs to see at a glance which robots the fleet has
            # cut off, and that is not expressible as a hardware state.
            "s": ("QUARANTINED" if self.quarantined else self.status.value),"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """            "rogue": self.rogue,"""
new = """            "rogue": self.rogue,
            # Where this robot CLAIMS to be, when that differs from where it
            # is. None for every honest robot, so the frame does not grow.
            # The map draws truth solid and the claim as a ghost, which is what
            # makes the lie visible rather than merely counted.
            "cl": ([round(self.claimed_x, 3), round(self.claimed_y, 3)]
                   if self.rogue and (self.spoof_x or self.spoof_y) else None),"""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(ROBOT, "w").write(src)
print("robot.py patched OK")
