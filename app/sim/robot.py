"""SWARMOS M5 simulation - robot physics and heterogeneous fleet specs.

This module owns the TRUE physical state of every robot. Nothing outside the
simulation package is permitted to mutate it (architectural law 1).

Two distinct state views exist on purpose:

  - true state    : exact physics, used for collision accounting and scoring
  - reported state: true state passed through the SensingProfile, this is the
                    only thing coordination and the UI are allowed to observe

Feature X-17 (heterogeneous fleet) lives here: PayloadClass and SpeedClass
give each robot different capability, and those capabilities gate bidding in
M4 so that a light robot cannot win a heavy task.
"""

from __future__ import annotations

import enum
import math
import random
from dataclasses import dataclass, field
from typing import Optional

from app.coordination.models import (
    AMRState,
    MovementIntent,
    Position,
    RobotStatus,
)
from app.sim.sensing import SensingProfile, SENSING_IDEAL
from app.sim.warehouse import ROBOT_RADIUS_M, Warehouse

TWO_PI = 2.0 * math.pi

# Battery model. Values are per second of simulated time.
IDLE_DRAIN_PCT_PER_S = 0.002
MOVE_DRAIN_PCT_PER_S = 0.020
PAYLOAD_DRAIN_PCT_PER_KG_S = 0.0004

# Below this level a robot must charge before accepting more work. The M4
# battery feasibility veto (X-18) uses the same number.
BATTERY_RESERVE_PCT = 15.0

# Arrival tolerance in metres. A waypoint is consumed when the robot is this
# close to it.
WAYPOINT_TOLERANCE_M = 0.08


class PayloadClass(str, enum.Enum):
    """What mass a robot can physically carry."""

    LIGHT = "LIGHT"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"

    @property
    def capacity_kg(self) -> float:
        return {"LIGHT": 15.0, "STANDARD": 60.0, "HEAVY": 200.0}[self.value]


class SpeedClass(str, enum.Enum):
    """How fast a robot can travel and how hard it can brake."""

    SLOW = "SLOW"
    NOMINAL = "NOMINAL"
    FAST = "FAST"

    @property
    def max_speed_mps(self) -> float:
        return {"SLOW": 0.6, "NOMINAL": 1.2, "FAST": 2.0}[self.value]

    @property
    def accel_mps2(self) -> float:
        return {"SLOW": 0.4, "NOMINAL": 0.8, "FAST": 1.2}[self.value]


@dataclass(frozen=True)
class RobotSpec:
    """Immutable capability record for one robot.

    Coordination reads this to decide whether a robot is even eligible to bid
    on a task. Making it immutable means a robot cannot quietly upgrade itself
    mid-run to win an auction, which is also what the rogue detector (X-10)
    relies on.
    """

    payload_class: PayloadClass = PayloadClass.STANDARD
    speed_class: SpeedClass = SpeedClass.NOMINAL
    charge_rate_pct_per_s: float = 0.5
    radius_m: float = ROBOT_RADIUS_M

    @property
    def capacity_kg(self) -> float:
        return self.payload_class.capacity_kg

    @property
    def max_speed_mps(self) -> float:
        return self.speed_class.max_speed_mps

    @property
    def accel_mps2(self) -> float:
        return self.speed_class.accel_mps2

    def can_carry(self, payload_kg: float) -> bool:
        return payload_kg <= self.capacity_kg

    def as_dict(self) -> dict:
        return {
            "payload_class": self.payload_class.value,
            "speed_class": self.speed_class.value,
            "capacity_kg": self.capacity_kg,
            "max_speed_mps": self.max_speed_mps,
            "charge_rate_pct_per_s": self.charge_rate_pct_per_s,
            "radius_m": self.radius_m,
        }


# The three specs used by the standard fleet, in the mix order applied by the
# engine. Keeping this as a module constant keeps fleet construction
# deterministic without needing the RNG.
FLEET_MIX: tuple[RobotSpec, ...] = (
    RobotSpec(PayloadClass.STANDARD, SpeedClass.NOMINAL, 0.50),
    RobotSpec(PayloadClass.LIGHT, SpeedClass.FAST, 0.65),
    RobotSpec(PayloadClass.STANDARD, SpeedClass.NOMINAL, 0.50),
    RobotSpec(PayloadClass.HEAVY, SpeedClass.SLOW, 0.35),
)


def normalise_heading(theta: float) -> float:
    """Fold any angle into [0, 2*pi) so AMRState validation always passes."""
    wrapped = math.fmod(theta, TWO_PI)
    if wrapped < 0.0:
        wrapped += TWO_PI
    # fmod can return exactly TWO_PI for tiny negative inputs after the add.
    if wrapped >= TWO_PI:
        wrapped = 0.0
    return wrapped


@dataclass
class SimRobot:
    """One robot inside the simulation.

    Fields prefixed by nothing are TRUE state. The reported_* fields are the
    noised view that leaves the simulation. With SENSING_IDEAL the two are
    identical, which is the default so the demo stays clean.
    """

    robot_id: str
    spec: RobotSpec
    x: float
    y: float
    heading: float = 0.0
    velocity: float = 0.0
    battery: float = 100.0
    status: RobotStatus = RobotStatus.AVAILABLE

    current_task_id: Optional[str] = None
    carrying_kg: float = 0.0

    # Metre-space waypoints the robot is currently following. Index 0 is the
    # next point to reach. The engine writes this, never coordination.
    path: list[tuple[float, float]] = field(default_factory=list)
    target: Optional[tuple[float, float]] = None
    intent_id: Optional[str] = None
    path_version: int = 1

    # Speed cap imposed by the last coordination verdict. 1.0 is PROCEED,
    # 0.0 is a hard WAIT, intermediate values are the SLOW rung of the ladder.
    speed_scale: float = 1.0

    # Set true by a fault injection. A failed robot stops integrating motion
    # and stops emitting heartbeats, which is what the M4 failure detector
    # (X-23) is meant to notice.
    failed: bool = False

    # Set true by a fault injection. A rogue robot broadcasts a position it is
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
    # X-01 mirror of the arbiter's sovereign set. Display and reporting only:
    # unlike quarantined it does NOT stop the robot and does NOT release its
    # task, because continuing to work is precisely what is being demonstrated.
    sovereign: bool = False

    # Reported (noised) view.
    reported_x: float = 0.0
    reported_y: float = 0.0
    drift_x: float = 0.0
    drift_y: float = 0.0

    # Odometry bookkeeping.
    distance_travelled_m: float = 0.0
    tasks_completed: int = 0

    def __post_init__(self) -> None:
        self.heading = normalise_heading(self.heading)
        self.reported_x = self.x
        self.reported_y = self.y

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    @property
    def position(self) -> tuple[float, float]:
        return (self.x, self.y)

    @property
    def is_idle(self) -> bool:
        return self.current_task_id is None and not self.path

    @property
    def needs_charge(self) -> bool:
        return self.battery <= BATTERY_RESERVE_PCT

    @property
    def is_available_for_work(self) -> bool:
        if self.failed:
            return False
        if self.quarantined:
            # Containment is a fleet decision, but eligibility is decided
            # here, so it has to be honoured here too - otherwise the
            # dispatcher quietly undoes it one tick later.
            return False
        if self.status in (RobotStatus.FAILED, RobotStatus.CHARGING):
            return False
        if self.current_task_id is not None:
            return False
        return not self.needs_charge

    def distance_to(self, px: float, py: float) -> float:
        return math.hypot(px - self.x, py - self.y)

    def remaining_path_length_m(self) -> float:
        """Length of the path still to be driven, starting from here."""
        if not self.path:
            return 0.0
        total = math.hypot(self.path[0][0] - self.x, self.path[0][1] - self.y)
        for a, b in zip(self.path, self.path[1:]):
            total += math.hypot(b[0] - a[0], b[1] - a[1])
        return total

    def eta_s(self) -> Optional[float]:
        """Optimistic ETA at full allowed speed. None when there is no path."""
        if not self.path:
            return None
        speed = self.spec.max_speed_mps
        if speed <= 0.0:
            return None
        return self.remaining_path_length_m() / speed

    # ------------------------------------------------------------------
    # commands issued by the engine
    # ------------------------------------------------------------------
    def assign_path(
        self,
        waypoints: list[tuple[float, float]],
        *,
        intent_id: str,
        target: Optional[tuple[float, float]] = None,
    ) -> None:
        self.path = list(waypoints)
        self.target = target if target is not None else (
            waypoints[-1] if waypoints else None
        )
        self.intent_id = intent_id
        self.path_version += 1

    def clear_path(self) -> None:
        self.path = []
        self.target = None
        self.intent_id = None
        self.velocity = 0.0

    def apply_verdict_scale(self, scale: float) -> None:
        """Apply the coordination speed cap. Clamped to a sane range."""
        self.speed_scale = min(1.0, max(0.0, scale))

    # ------------------------------------------------------------------
    # physics
    # ------------------------------------------------------------------
    def step(self, dt_s: float, rng: random.Random, sensing: SensingProfile) -> float:
        """Advance this robot by dt_s. Returns metres travelled this tick.

        Motion is a straight chase of the next waypoint with trapezoidal speed
        limiting. This is intentionally simple: the interesting behaviour in
        SWARMOS is the coordination, and a simple integrator keeps the run
        bit-for-bit reproducible.
        """
        if self.failed:
            self.velocity = 0.0
            self.status = RobotStatus.FAILED
            self._update_reported(0.0, rng, sensing)
            return 0.0

        if self.status == RobotStatus.CHARGING:
            self.velocity = 0.0
            self.battery = min(
                100.0, self.battery + self.spec.charge_rate_pct_per_s * dt_s
            )
            if self.battery >= 95.0:
                self.status = RobotStatus.AVAILABLE
            self._update_reported(0.0, rng, sensing)
            return 0.0

        allowed = self.spec.max_speed_mps * self.speed_scale

        if not self.path or allowed <= 0.0:
            # Either nothing to do, or coordination told us to hold.
            self.velocity = 0.0
            if self.path and allowed <= 0.0:
                self.status = RobotStatus.WAITING
            elif self.current_task_id is None:
                self.status = RobotStatus.AVAILABLE
            self._drain(dt_s, moving=False)
            self._update_reported(0.0, rng, sensing)
            return 0.0

        self.status = RobotStatus.MOVING

        # Accelerate toward the allowed speed.
        self.velocity = min(allowed, self.velocity + self.spec.accel_mps2 * dt_s)

        budget = self.velocity * dt_s
        moved = 0.0

        while budget > 1e-12 and self.path:
            wx, wy = self.path[0]
            dx, dy = wx - self.x, wy - self.y
            leg = math.hypot(dx, dy)

            if leg <= WAYPOINT_TOLERANCE_M and leg <= budget:
                # Snap exactly onto the waypoint so accumulated float error
                # cannot drift a robot off the aisle centreline.
                #
                # The snap is charged against the budget, and is taken only when
                # the budget can afford it. It used to be free: neither `moved`
                # nor `budget` was touched, so a robot could gain up to
                # WAYPOINT_TOLERANCE_M of displacement per waypoint per tick on
                # top of whatever its speed allowed. That broke the invariant the
                # coordination layer depends on - that granting speed_scale f
                # moves a robot at most f * MAX_STEP_M - and it cost real
                # collisions: a step the safety monitor cleared with 0.0039 m of
                # margin overshot into the 0.75 m hard-stop floor, reaching
                # 0.6962 m. See docs/SUCCESS_CRITERIA_VERIFICATION.md, C1.
                #
                # An unaffordable near-waypoint falls through to the ratio branch
                # below and snaps on a later tick, so the anti-drift guarantee is
                # kept without granting motion nobody authorised.
                self.x, self.y = wx, wy
                self.path.pop(0)
                moved += leg
                budget -= leg
                continue

            self.heading = normalise_heading(math.atan2(dy, dx))

            if leg <= budget:
                self.x, self.y = wx, wy
                self.path.pop(0)
                moved += leg
                budget -= leg
            else:
                ratio = budget / leg
                self.x += dx * ratio
                self.y += dy * ratio
                moved += budget
                budget = 0.0

        if not self.path:
            self.velocity = 0.0
            self.target = None

        self.distance_travelled_m += moved
        self._drain(dt_s, moving=moved > 0.0)
        self._update_reported(moved, rng, sensing)
        return moved

    def _drain(self, dt_s: float, *, moving: bool) -> None:
        rate = MOVE_DRAIN_PCT_PER_S if moving else IDLE_DRAIN_PCT_PER_S
        rate += PAYLOAD_DRAIN_PCT_PER_KG_S * self.carrying_kg
        self.battery = max(0.0, self.battery - rate * dt_s)
        if self.battery <= 0.0:
            # A flat battery is a stall, not a crash. The failure detector
            # still sees the robot, it simply stops making progress.
            self.velocity = 0.0
            self.status = RobotStatus.BLOCKED

    @property
    def claimed_x(self) -> float:
        """The x this robot tells its peers it is at.

        Equal to reported_x for every honest robot. The spoof offset is kept
        separate from drift and jitter on purpose: sensor error is something
        that happens TO a robot and is bounded by the sensing profile, whereas
        this is something the robot does, and the two must never be summed into
        one unexplainable number.
        """
        return self.reported_x + (self.spoof_x if self.rogue else 0.0)

    @property
    def claimed_y(self) -> float:
        return self.reported_y + (self.spoof_y if self.rogue else 0.0)

    def _update_reported(
        self, moved_m: float, rng: random.Random, sensing: SensingProfile
    ) -> None:
        """Recompute the observable position from true position plus noise.

        All randomness comes from the engine RNG, so determinism survives even
        with the realistic sensing profile enabled.
        """
        if not sensing.enabled:
            self.reported_x = self.x
            self.reported_y = self.y
            return

        if sensing.odometry_drift_m_per_m > 0.0 and moved_m > 0.0:
            scale = sensing.odometry_drift_m_per_m * moved_m
            self.drift_x += rng.gauss(0.0, scale)
            self.drift_y += rng.gauss(0.0, scale)

        sigma = sensing.localisation_sigma_m
        jitter_x = rng.gauss(0.0, sigma) if sigma > 0.0 else 0.0
        jitter_y = rng.gauss(0.0, sigma) if sigma > 0.0 else 0.0

        self.reported_x = self.x + self.drift_x + jitter_x
        self.reported_y = self.y + self.drift_y + jitter_y

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def to_amr_state(self, timestamp: float, *, reported: bool = True) -> AMRState:
        """Produce the canonical AMRState from app.coordination.models.

        reported=True is the normal path: coordination and the UI see the
        sensed view. reported=False is used only by the safety monitor and the
        scorer, which are entitled to ground truth.
        """
        if reported:
            # The broadcast view. For an honest robot this is true position
            # plus sensor error; for a rogue robot the deliberate offset is
            # added here, because this is the only place the outside world
            # reads a position from, and so the only place a lie can live.
            px, py = self.claimed_x, self.claimed_y
        else:
            px, py = self.x, self.y

        intent: Optional[MovementIntent] = None
        if self.path and self.intent_id is not None:
            tx, ty = self.target if self.target is not None else self.path[-1]
            intent = MovementIntent(
                target=Position(x=tx, y=ty),
                path=[Position(x=wx, y=wy) for wx, wy in self.path],
                eta=self.eta_s(),
                intent_id=self.intent_id,
                path_version=self.path_version,
            )

        return AMRState(
            robot_id=self.robot_id,
            timestamp=timestamp,
            position=Position(x=px, y=py),
            velocity=self.velocity,
            heading=self.heading,
            status=self.status,
            battery=self.battery,
            current_task_id=self.current_task_id,
            movement_intent=intent,
        )

    def as_render_dict(self) -> dict:
        """Compact per-tick payload for the frontend.

        Keys are short and values rounded because this crosses the websocket
        50 times per tick at 10 Hz. Rounding is to millimetres and
        milliradians, far below anything a 60 fps canvas can show.
        """
        return {
            "id": self.robot_id,
            "x": round(self.reported_x, 3),
            "y": round(self.reported_y, 3),
            "h": round(self.heading, 3),
            "v": round(self.velocity, 3),
            "b": round(self.battery, 1),
            # QUARANTINED and SOVEREIGN override the lifecycle status for
            # display only, and QUARANTINED outranks SOVEREIGN: a contained liar
            # is the more urgent fact about a robot than a lost radio, and an
            # operator shown only "SOVEREIGN" for a quarantined rogue would be
            # actively misled.
            "s": (
                "QUARANTINED" if self.quarantined
                else "SOVEREIGN" if self.sovereign
                else self.status.value
            ),
            "t": self.current_task_id,
            "pc": self.spec.payload_class.value,
            "sc": self.spec.speed_class.value,
            "rogue": self.rogue,
            # Where this robot CLAIMS to be, when that differs from where it
            # is. None for every honest robot, so the frame does not grow.
            # The map draws truth solid and the claim as a ghost, which is what
            # makes the lie visible rather than merely counted.
            "cl": ([round(self.claimed_x, 3), round(self.claimed_y, 3)]
                   if self.rogue and (self.spoof_x or self.spoof_y) else None),
            # Remaining path as a flat coordinate array, and the committed
            # goal. Flat because an object per waypoint roughly triples the
            # frame at 50 robots x 10 Hz for no extra information.
            "p": [round(c, 2) for wp in self.path for c in wp],
            "tg": ([round(self.target[0], 2), round(self.target[1], 2)]
                   if self.target is not None else None),
            "pv": self.path_version,
        }


def spawn_fleet(
    warehouse: Warehouse,
    count: int,
    rng: random.Random,
) -> list[SimRobot]:
    """Create `count` robots on distinct navigable cells.

    Spawn cells are drawn from a sorted candidate list using the seeded RNG so
    that the same seed always produces the same starting formation.
    """
    candidates = [
        (cx, cy)
        for cy in range(warehouse.height)
        for cx in range(warehouse.width)
        if warehouse.is_navigable(cx, cy)
    ]
    if len(candidates) < count:
        raise ValueError(
            f"warehouse has {len(candidates)} navigable cells, cannot spawn {count}"
        )

    chosen = rng.sample(candidates, count)
    robots: list[SimRobot] = []
    for index, (cx, cy) in enumerate(chosen):
        x, y = warehouse.cell_to_m(cx, cy)
        spec = FLEET_MIX[index % len(FLEET_MIX)]
        robots.append(
            SimRobot(
                robot_id=f"R{index + 1:03d}",
                spec=spec,
                x=x,
                y=y,
                heading=0.0,
                battery=100.0 - rng.uniform(0.0, 20.0),
            )
        )
    return robots

# File contains AI-generated response based on internal company sources
