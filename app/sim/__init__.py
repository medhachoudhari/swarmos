"""
M5 Simulation - the SINGLE authoritative source of robot state.

Architectural Law 1: nothing outside this package writes robot state. M4
coordination issues verdicts, M3 offers advice, M2 transports and M1 renders;
only the simulation engine here mutates an AMRState.

Public surface:
    Warehouse        static geometry, grid <-> metre conversion, occupancy
    RobotSpec        heterogeneous capability profile (X-17)
    Task, Priority   task stream with deadlines and SLA classes (X-16)
    SimClock         fixed 10 Hz tick, seeded and deterministic
    SimEngine        the tick loop and the only writer of AMRState
    SENSING          noise / drift / delay hooks (X-15 hooks, UI deferred)
    SCENARIOS        rush_50, narrow_aisle_deadlock, blocked_aisle
"""

from app.sim.warehouse import Warehouse, Cell, Zone
from app.sim.tasks import Task, TaskPriority, TaskStatus, TaskGenerator
from app.sim.robot import RobotSpec, PayloadClass, SpeedClass, SimRobot
from app.sim.clock import SimClock, TICK_HZ, TICK_SECONDS
from app.sim.sensing import SensingProfile, SENSING_IDEAL, SENSING_REALISTIC
from app.sim.pathfinding import find_path, nearest_navigable, path_to_metres
from app.sim.policy import (
    CoordinationPolicy,
    NoOpPolicy,
    StopAndWaitPolicy,
    Verdict,
    VerdictKind,
    R_COMM_M,
)
from app.sim.engine import SimEngine, SimSnapshot, Violation, COLLISION_DISTANCE_M
from app.sim.scenarios import (
    SCENARIOS,
    DEFAULT_SCENARIO,
    ScenarioSpec,
    Injection,
    FaultKind,
    get_scenario,
    list_scenarios,
    scalability_variants,
)

__all__ = [
    "Warehouse", "Cell", "Zone",
    "Task", "TaskPriority", "TaskStatus", "TaskGenerator",
    "RobotSpec", "PayloadClass", "SpeedClass", "SimRobot",
    "SimClock", "TICK_HZ", "TICK_SECONDS",
    "SensingProfile", "SENSING_IDEAL", "SENSING_REALISTIC",
    "find_path", "nearest_navigable", "path_to_metres",
    "CoordinationPolicy", "NoOpPolicy", "StopAndWaitPolicy",
    "Verdict", "VerdictKind", "R_COMM_M",
    "SimEngine", "SimSnapshot", "Violation", "COLLISION_DISTANCE_M",
    "SCENARIOS", "DEFAULT_SCENARIO", "ScenarioSpec", "Injection", "FaultKind",
    "get_scenario", "list_scenarios", "scalability_variants",
]


# File contains AI-generated response based on internal company sources
