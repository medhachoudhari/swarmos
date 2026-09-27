"""SWARMOS M5 simulation - scenario definitions and fault injections.

Scope decision (cut S-06): the original six scenarios are reduced to THREE
real scenarios, because two of the original six were not scenarios at all,
they were fault injections that can be fired inside any scenario:

  kept as scenarios      : rush_50, narrow_aisle_deadlock, blocked_aisle
  demoted to injections  : battery_crisis, robot_failure  (plus rogue_robot)

That is a reduction in surface, not in capability: every original behaviour is
still reachable, and the operator can now combine them (for example a robot
failure during rush_50), which the six-scenario menu could not do.

A ScenarioSpec is pure data. The engine reads it; nothing here mutates state.
An injection is a (tick, FaultKind, params) triple, so a scenario is fully
reproducible from its spec plus the seed.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Optional

from app.sim.clock import TICK_HZ
from app.sim.sensing import SENSING_IDEAL, SENSING_REALISTIC, SensingProfile


class FaultKind(str, enum.Enum):
    """Everything that can go wrong, as an explicit injectable event.

    Each of these maps to exactly one handler in SimEngine._apply_fault, and
    each one exists to make a specific claim demonstrable on stage:

      ROBOT_FAILURE  proves the X-23 failure detector and reservation GC
      BATTERY_DRAIN  proves the X-18 battery feasibility veto
      BLOCK_AISLE    proves reroute and the verdict ladder
      ROGUE_ROBOT    proves X-10 quarantine
      LINK_IMPAIR    proves X-02 impairment tolerance
      ZONE_PARTITION proves the NO_NETWORK rung of the degradation ladder
      TASK_BURST     proves throughput under load
      KILL_ML        proves the safety firewall is not in the ML path
    """

    ROBOT_FAILURE = "ROBOT_FAILURE"
    BATTERY_DRAIN = "BATTERY_DRAIN"
    BLOCK_AISLE = "BLOCK_AISLE"
    CLEAR_BLOCKAGE = "CLEAR_BLOCKAGE"
    ROGUE_ROBOT = "ROGUE_ROBOT"
    LINK_IMPAIR = "LINK_IMPAIR"
    ZONE_PARTITION = "ZONE_PARTITION"
    TASK_BURST = "TASK_BURST"
    KILL_ML = "KILL_ML"
    # X-01. Cuts one robot's radio in both directions. Proves that a robot which
    # can no longer coordinate keeps working under a tighter envelope instead of
    # stopping and blocking an aisle, and rejoins the moment it is audible again.
    COMM_BLACKOUT = "COMM_BLACKOUT"


@dataclass(frozen=True)
class Injection:
    """One fault scheduled at a specific tick.

    at_tick is a tick index, not a wall-clock time, because wall clock is not
    reproducible. at_second is provided only as a convenience constructor.
    """

    at_tick: int
    kind: FaultKind
    params: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def at_second(at_s: float, kind: FaultKind, **params: Any) -> "Injection":
        return Injection(at_tick=int(round(at_s * TICK_HZ)), kind=kind, params=params)

    def as_dict(self) -> dict:
        return {
            "at_tick": self.at_tick,
            "at_s": round(self.at_tick / TICK_HZ, 2),
            "kind": self.kind.value,
            "params": dict(self.params),
        }


@dataclass(frozen=True)
class ScenarioSpec:
    """Complete, reproducible description of one run.

    Given (ScenarioSpec, seed) the engine must produce a bit-identical trace.
    That is the contract the X-22 trace hash verifies, so every field that can
    influence behaviour has to live here - nothing may be read from the
    environment or the wall clock.
    """

    name: str
    title: str
    description: str
    proves: str

    fleet_size: int = 50
    width: int = 60
    height: int = 40

    # Task arrival model.
    task_rate_per_s: float = 1.2
    initial_burst: int = 0

    # Optional hard stop. None means run until the operator stops it.
    duration_s: Optional[float] = None

    sensing: SensingProfile = SENSING_IDEAL
    injections: tuple[Injection, ...] = ()

    # Narrow-aisle variants make the grid tighter by removing cross aisles,
    # which is what actually manufactures head-on conflict.
    aisle_period: int = 4
    cross_period: int = 10
    # 2 gives two-way main aisles, which is what real distribution centres
    # build. 1 forces strictly single-file traffic, which is a wedge generator
    # and is used only by narrow_aisle_deadlock.
    aisle_width: int = 2
    cross_width: int = 2

    @property
    def duration_ticks(self) -> Optional[int]:
        if self.duration_s is None:
            return None
        return int(round(self.duration_s * TICK_HZ))

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "proves": self.proves,
            "fleet_size": self.fleet_size,
            "width": self.width,
            "height": self.height,
            "task_rate_per_s": self.task_rate_per_s,
            "initial_burst": self.initial_burst,
            "duration_s": self.duration_s,
            "aisle_period": self.aisle_period,
            "cross_period": self.cross_period,
            "aisle_width": self.aisle_width,
            "cross_width": self.cross_width,
            "sensing": self.sensing.as_dict(),
            "injections": [i.as_dict() for i in self.injections],
        }


# ----------------------------------------------------------------------
# The three scenarios
# ----------------------------------------------------------------------

RUSH_50 = ScenarioSpec(
    name="rush_50",
    title="Rush hour, 50 robots",
    description=(
        "Fifty heterogeneous robots on the full floor with a 30-task opening "
        "burst and a sustained 1.5 tasks/s arrival rate. This is the default "
        "state the demo opens in."
    ),
    proves=(
        "Sustained 10 Hz coordination at fleet scale, zero collisions, and the "
        "throughput lead over the stop-and-wait baseline."
    ),
    fleet_size=50,
    task_rate_per_s=1.5,
    initial_burst=30,
    duration_s=None,
)

NARROW_AISLE_DEADLOCK = ScenarioSpec(
    name="narrow_aisle_deadlock",
    title="Narrow aisle deadlock",
    description=(
        "Cross aisles removed so every aisle is a single-file corridor with "
        "only two exits. Robots are forced into head-on and swap conflicts "
        "that a naive first-come planner deadlocks on."
    ),
    proves=(
        "Deadlock detection and the graded verdict ladder, plus deterministic "
        "lock arbitration when two robots claim the same cell on the same tick."
    ),
    fleet_size=24,
    width=40,
    height=28,
    aisle_period=3,
    cross_period=999,          # effectively no cross aisles
    aisle_width=1,             # strictly single file - the wedge is the point
    cross_width=1,
    task_rate_per_s=0.9,
    initial_burst=16,
    duration_s=180.0,
)

BLOCKED_AISLE = ScenarioSpec(
    name="blocked_aisle",
    title="Aisle blocked mid-run",
    description=(
        "A busy run where a central aisle segment is sealed at t=20 s and "
        "reopened at t=80 s, invalidating in-flight reservations and forcing "
        "a fleet-wide reroute."
    ),
    proves=(
        "Reservation invalidation, replanning under a changed map, and that "
        "the safety invariant counter stays at zero through the disruption."
    ),
    fleet_size=40,
    task_rate_per_s=1.2,
    initial_burst=20,
    duration_s=150.0,
    injections=(
        Injection.at_second(20.0, FaultKind.BLOCK_AISLE, cx=30, cy0=8, cy1=30),
        Injection.at_second(80.0, FaultKind.CLEAR_BLOCKAGE),
    ),
)


SCENARIOS: dict[str, ScenarioSpec] = {
    s.name: s for s in (RUSH_50, NARROW_AISLE_DEADLOCK, BLOCKED_AISLE)
}

DEFAULT_SCENARIO = "rush_50"


def get_scenario(name: str) -> ScenarioSpec:
    """Look up a scenario by name, raising a helpful error on a typo."""
    try:
        return SCENARIOS[name]
    except KeyError:
        known = ", ".join(sorted(SCENARIOS))
        raise KeyError(
            f"unknown scenario '{name}', known scenarios: {known}"
        ) from None


def list_scenarios() -> list[dict]:
    """Menu payload for the Simulation Lab screen."""
    return [SCENARIOS[n].as_dict() for n in sorted(SCENARIOS)]


# ----------------------------------------------------------------------
# Benchmark variants
# ----------------------------------------------------------------------

def scalability_variants(
    base: str = "rush_50",
    sizes: tuple[int, ...] = (10, 25, 50, 100),
    duration_s: float = 120.0,
) -> list[ScenarioSpec]:
    """Fleet-size sweep for the X-14 scalability curve.

    Task rate scales with fleet size so that offered load per robot is held
    constant; otherwise a bigger fleet would look better purely because it was
    starved of work, which would be a dishonest curve.
    """
    spec = get_scenario(base)
    per_robot_rate = spec.task_rate_per_s / spec.fleet_size
    out: list[ScenarioSpec] = []
    for n in sizes:
        out.append(
            ScenarioSpec(
                name=f"{spec.name}_n{n}",
                title=f"{spec.title} ({n} robots)",
                description=(
                    f"Scalability point at {n} robots, load per robot held constant."
                ),
                proves="Messages per robot per tick stays flat as fleet size grows.",
                fleet_size=n,
                width=spec.width,
                height=spec.height,
                task_rate_per_s=round(per_robot_rate * n, 4),
                initial_burst=max(4, n // 2),
                duration_s=duration_s,
                aisle_period=spec.aisle_period,
                cross_period=spec.cross_period,
                aisle_width=spec.aisle_width,
                cross_width=spec.cross_width,
                sensing=spec.sensing,
            )
        )
    return out


def realistic_variant(name: str) -> ScenarioSpec:
    """Same scenario with localisation noise and actuation delay switched on.

    Used to show the coordination layer does not secretly depend on perfect
    state. Hooks are built now; the live UI controls for this are deferred.
    """
    spec = get_scenario(name)
    return ScenarioSpec(
        name=f"{spec.name}_realistic",
        title=f"{spec.title} (realistic sensing)",
        description=(
            spec.description + " Localisation noise and odometry drift enabled."
        ),
        proves="Safety holds when observed state is imperfect.",
        fleet_size=spec.fleet_size,
        width=spec.width,
        height=spec.height,
        task_rate_per_s=spec.task_rate_per_s,
        initial_burst=spec.initial_burst,
        duration_s=spec.duration_s,
        aisle_period=spec.aisle_period,
        cross_period=spec.cross_period,
        aisle_width=spec.aisle_width,
        cross_width=spec.cross_width,
        sensing=SENSING_REALISTIC,
        injections=spec.injections,
    )

# File contains AI-generated response based on internal company sources
