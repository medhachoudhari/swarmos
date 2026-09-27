"""SWARMOS M5 simulation - the tick engine.

This is the single authoritative writer of robot state (architectural law 1).
No other module in the project is permitted to mutate a SimRobot. Everything
else - coordination, ML, the API, the frontend - observes state through
snapshots and influences it only by returning Verdicts.

Tick order is fixed and must not be reordered, because the whole determinism
guarantee rests on it:

  1. apply scheduled fault injections for this tick
  2. generate newly arriving tasks
  3. dispatch pending tasks to eligible robots (capability and battery gated)
  4. plan or replan paths for robots that need one
  5. publish observed state, ask the policy to arbitrate, apply verdicts
  6. integrate motion for one dt
  7. resolve pick-ups, drop-offs and charging
  8. account safety invariants and update the rolling trace hash

Steps 5 and 6 are separated on purpose: arbitration always sees the state at
the START of the tick, identically for every robot, so no robot gains an
advantage from being evaluated later in the loop.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from app.coordination.models import AMRState, RobotStatus
from app.coordination.radio import LINK_PERFECT, LinkProfile
from app.ml.forecast import Forecaster
from app.sim.clock import TICK_HZ, TICK_SECONDS, SimClock
from app.sim.pathfinding import (
    find_path,
    nearest_navigable,
    path_to_metres,
    simplify_collinear,
    trim_passed_start,
)
from app.sim.policy import (
    CoordinationPolicy,
    NoOpPolicy,
    Verdict,
    VerdictKind,
)
from app.sim.robot import BATTERY_RESERVE_PCT, SimRobot, spawn_fleet
from app.sim.scenarios import DEFAULT_SCENARIO, FaultKind, ScenarioSpec, get_scenario
from app.sim.tasks import Task, TaskGenerator, TaskPriority, TaskStatus
from app.sim.warehouse import Cell, Warehouse

# Two robots closer than this are declared to be in physical contact. It is
# the sum of two footprint radii (0.35 + 0.35). This is the X-09 invariant and
# it is measured on TRUE positions, never on reported ones, so sensing noise
# can never be used to hide a collision.
# X-28 admission control. The fraction of the fleet that may hold a task at
# once. Measured at fleet 50: uncapped gives 14 completions and 1 collision,
# capped at 0.6 gives 22 and 0. See tools/patch_wip_cap.py for the full result.
WIP_FRACTION = 0.6

COLLISION_DISTANCE_M = 0.70

# A near miss is not a violation but it is worth counting: a design that only
# ever clears by a millimetre is not actually safe, it is lucky.
NEAR_MISS_DISTANCE_M = 1.00

# Pick and drop dwell, in ticks. Real AMRs need time under a rack.
DWELL_TICKS = 5

# Stalled-task release (fix for the fleet-50 gridlock defect, measured and
# documented in docs/GRIDLOCK_DEFECT_20260922.md).
#
# The safety monitor's own comments in swarm_policy.py._monitor() admit a
# KNOWN LIMITATION: once a pair of robots is already inside HARD_STOP_M, no
# fraction of a step clears the floor, so MONITOR_STUCK_TICKS keeps firing
# REROUTE, _plan() keeps handing back a path, and the pair keeps re-entering
# the same standoff - replans climb into the tens of thousands while true
# displacement stays exactly 0.0 m. That is not a path-planning bug (the robot
# is never left without a path - see _plan()'s `if robot.path: continue`
# guard, which _apply_verdicts already correctly bypasses on REROUTE) and
# fixing the monitor geometry itself was tried five times and rejected each
# time because it re-introduced collisions (see the version history in
# swarm_policy.py._monitor's docstring). So the fix here is the one the
# authors flagged as still open: stop retrying forever. A robot that holds a
# task but has made no measurable progress for STALL_RELEASE_TICKS gives the
# task back to the pending pool - the same "release, don't loop" recovery
# StopAndWaitPolicy already uses - so the fleet does not permanently lose
# capacity to a standoff that the monitor and the ladder cannot themselves
# resolve. This never overrides the safety kernel: it only decides who is
# allowed to keep trying.
STALL_EPS_M = 0.02
STALL_RELEASE_TICKS = 150       # 15 s of measured zero net progress

# Re-dispatch hold after a stall release (batch 1, docs/COORDINATION_FIXES_
# BATCH1.md). Releasing the task fixed the task, not the robot: the robot is
# still standing in the same standoff, and _dispatch used to hand it the very
# next job. Measured at fleet 50: 215 of 286 assignments went to robots that had
# not moved for 200+ ticks, and such robots held 18 of the 30 WIP slots, so
# healthy robots sat idle while work was pending. A released robot is therefore
# not offered new work until it is clear of every other robot by
# STALL_CLEARANCE_M (the near-miss distance: nobody left close enough to be the
# thing it was stuck against), or until STALL_RELEASE_TICKS more ticks have
# passed, whichever comes first - so the hold is bounded and can never disable a
# robot for good. Engine-level, so it applies identically to every policy.
STALL_CLEARANCE_M = 1.00

# Reporting threshold for the robots_stalled KPI (batch 2): 5 s holding a task
# without measurable progress. Display only; nothing acts on it.
STALL_REPORT_TICKS = 50


# How close a robot must be to a pick, drop or charger cell to service it.
#
# This MUST be larger than the safety separation any arbiter enforces (0.75 m
# for the stop-and-wait baseline), and the reason is subtle enough to be worth
# writing down. Stations are convergence points, so a queue forms behind them.
# If the service radius were tighter than the separation the arbiter insists
# on, the robot at the head of that queue could never legally close the last
# gap, every station would jam, and throughput would be exactly zero while
# every individual component still looked correct.
#
# 1.1 m is also the physically right number: it is one cell pitch plus a
# margin, and a real AMR services a rack face, pick station or charger from the
# adjacent aisle cell rather than by driving onto it.
SERVICE_RADIUS_M = 1.1

# Default duration of an injected LINK_IMPAIR or ZONE_PARTITION, in ticks
# (30 s at 10 Hz). Bounded, like COMM_BLACKOUT, so a demo injection degrades the
# fleet visibly and then recovers inside the same run.
COMM_FAULT_TICKS = 300

# Range of the onboard proximity stop, in metres. See _apply_onboard_brake.
ONBOARD_STOP_M = 0.90


@dataclass
class Violation:
    """One recorded breach of the safety invariant.

    Kept in full detail rather than as a bare counter, because a counter that
    only ever reads zero proves nothing. Being able to show what a violation
    record would look like is what makes the zero credible.
    """

    tick: int
    sim_time: float
    robot_a: str
    robot_b: str
    distance_m: float

    def as_dict(self) -> dict:
        return {
            "tick": self.tick,
            "sim_time": round(self.sim_time, 2),
            "robot_a": self.robot_a,
            "robot_b": self.robot_b,
            "distance_m": round(self.distance_m, 4),
        }


@dataclass
class SimSnapshot:
    """Immutable per-tick view handed to the API, the recorder and the UI.

    Deliberately plain dicts and floats: this object is serialised to JSON ten
    times a second, so it must not carry pydantic models or live references
    into engine internals.
    """

    tick: int
    sim_time: float
    timestamp: float
    robots: list[dict]
    verdicts: list[dict]
    tasks_pending: int
    tasks_active: int
    tasks_complete: int
    kpis: dict
    events: list[dict]
    trace_hash: str

    def as_dict(self) -> dict:
        return {
            "tick": self.tick,
            "sim_time": round(self.sim_time, 2),
            "timestamp": self.timestamp,
            "robots": self.robots,
            "verdicts": self.verdicts,
            "tasks": {
                "pending": self.tasks_pending,
                "active": self.tasks_active,
                "complete": self.tasks_complete,
            },
            "kpis": self.kpis,
            "events": self.events,
            "trace_hash": self.trace_hash,
        }


class SimEngine:
    """The warehouse simulation.

    Construct with a scenario and a seed, then call step() at 10 Hz. Two
    engines built with the same (scenario, seed) and driven with equivalent
    policies produce identical trace hashes; that is asserted by the
    determinism test and shown live in the status bar (X-22).
    """

    def __init__(
        self,
        scenario: ScenarioSpec | str = DEFAULT_SCENARIO,
        *,
        seed: int = 42,
        policy: Optional[CoordinationPolicy] = None,
        label: str = "swarmos",
    ) -> None:
        self.scenario = (
            get_scenario(scenario) if isinstance(scenario, str) else scenario
        )
        self.seed = int(seed)
        self.label = label

        # One RNG for everything. Every stochastic decision in the simulation
        # draws from this stream in a fixed order, which is what makes the run
        # reproducible from the seed alone.
        self.rng = random.Random(self.seed)

        self.clock = SimClock()
        self.warehouse = Warehouse.standard(
            width=self.scenario.width,
            height=self.scenario.height,
            aisle_period=self.scenario.aisle_period,
            cross_period=self.scenario.cross_period,
            aisle_width=self.scenario.aisle_width,
            cross_width=self.scenario.cross_width,
        )
        self.sensing = self.scenario.sensing
        self.policy: CoordinationPolicy = policy if policy is not None else NoOpPolicy()

        # X-01. tick at which each silenced robot's radio comes back. Engine
        # state rather than radio state, because the radio's job is to model
        # reachability, not to schedule the operator's faults.
        self._blackout_until: dict[str, int] = {}

        self.robots: dict[str, SimRobot] = {
            r.robot_id: r
            for r in spawn_fleet(self.warehouse, self.scenario.fleet_size, self.rng)
        }

        self.pick_cells = self.warehouse.cells_of_type(Cell.PICK)
        self.drop_cells = self.warehouse.cells_of_type(Cell.DROP)
        self.charger_cells = self.warehouse.cells_of_type(Cell.CHARGER)

        self.task_gen = TaskGenerator(
            pick_cells=self.pick_cells,
            drop_cells=self.drop_cells,
            rate_per_s=self.scenario.task_rate_per_s,
            seed=self.seed + 1,     # separate stream so fleet size cannot
                                    # change the task sequence
        )

        self.tasks: dict[str, Task] = {}
        self.pending: list[str] = []          # task ids, FIFO within priority
        self.completed: list[str] = []

        # Per-robot transient bookkeeping.
        self._dwell: dict[str, int] = {}
        self._goal_cell: dict[str, tuple[int, int]] = {}
        self._phase: dict[str, str] = {}      # "TO_PICK" | "TO_DROP" | "TO_CHARGER"
        self._intent_counter = 0

        # Cells the next replan for this robot must treat as impassable.
        #
        # This is what makes a REROUTE verdict mean anything. An arbiter that
        # says "replan" without saying what to avoid gets the identical A* path
        # straight back, because A* only knows about racks and blockages, not
        # about the peer that is standing in the way. The robot then re-enters
        # the same wedge, is held again, reroutes again, and the fleet livelocks
        # while the logs cheerfully report thousands of successful replans.
        # Feeding the named blocker's cell in as a temporary obstacle forces a
        # genuinely different route, which is the honest classical recovery.
        self._avoid_hint: dict[str, set[tuple[int, int]]] = {}

        # Stall tracking for STALL_RELEASE_TICKS (see the constant's comment).
        # Maps robot_id -> (last_progress_tick, x, y) as of the last tick that
        # robot was measured to have moved at least STALL_EPS_M from where it
        # was the previous time this was checked.
        self._stall: dict[str, tuple[int, float, float]] = {}
        self.stall_releases = 0
        # robot_id -> tick of its last stall release, while the re-dispatch
        # hold (STALL_CLEARANCE_M) is still in force.
        self._stall_hold: dict[str, int] = {}
        self.stall_holds_skipped = 0

        # Safety and metrics.
        self.violations: list[Violation] = []

        self.near_misses = 0
        # Pairs currently inside COLLISION_DISTANCE_M. A Violation is recorded
        # only when a pair ENTERS this set, so one frozen overlap is one
        # collision rather than one per tick for the rest of the run. See
        # SESSION_SUMMARY_20260921_0020_collision_metric_defect.md.
        self._overlapping: set[tuple[str, str]] = set()
        # Pair-ticks spent overlapping. This is what `collisions` used to
        # measure. Kept because how long a breach persists matters, but it is
        # a dwell metric and must never be reported as a collision count.
        self.overlap_ticks = 0
        self.verdict_counts: dict[str, int] = {k.value: 0 for k in VerdictKind}
        # Telemetry (batch 2). `replans` used to be incremented both when a
        # path was cleared and again when the next one was planned, and it
        # also counted every first plan for a new goal - so the REPLANS
        # figure on screen was neither replans nor plans. Now:
        #   path_plans          every path handed to a robot
        #   initial_plans       plans for a new goal
        #   replans             plans that replace an invalidated path
        #   path_invalidations  paths cleared by a verdict or an invalidation
        self.replans = 0
        self.initial_plans = 0
        self.path_plans = 0
        self.path_invalidations = 0
        self._replan_due: set[str] = set()
        self.veto_battery = 0
        self.veto_capability = 0
        self.events: list[dict] = []
        self._events_this_tick: list[dict] = []

        self._last_verdicts: dict[str, Verdict] = {}

        # M3 advisory layer. The forecaster observes the same published state
        # the arbiter sees and proposes speed reductions. Its output is written
        # onto the snapshot for display and is never passed to the policy, so
        # deleting it or feeding it garbage cannot change robot behaviour or the
        # trace hash. tests/test_ml.py proves that rather than asserting it.
        #
        # X-05, measured 2026-09-21, do NOT promote this into the planner.
        # Scored against a persistence baseline on identical (zone, target
        # tick) pairs by tools/measure_forecast.py, 1800 ticks, seeds
        # 11/13/17, rush_50:
        #   fleet  8: model MAE 5.344 vs persistence 0.667 (701 pct worse)
        #   fleet 50: model MAE 2.308 vs persistence 0.415 (456 pct worse)
        # A linear slope over a 20 tick horizon overshoots because robot
        # flow is bursty, not linear. It loses to guessing 'the zone holds
        # what it holds now', so it may not steer routing. The fence is
        # enforced by tests/test_ml_fence.py; reasoning in
        # docs/X05_FORECASTER_DECISION.md.
        self.forecaster = Forecaster()
        self.ml_enabled = True
        self._last_advisories: dict = {}
        self.advisories_proposed = 0
        self.advisories_overridden = 0
        self.advisories_agreed = 0
        self.ml_errors = 0
        self.ml_last_error: Optional[str] = None
        self._override_pairs: dict[str, int] = {}
        self._hash = hashlib.blake2b(digest_size=8)
        self._hash.update(
            f"{self.scenario.name}|{self.seed}|{self.policy.name}".encode()
        )

        self._injections = sorted(
            self.scenario.injections, key=lambda i: (i.at_tick, i.kind.value)
        )
        self._next_injection = 0
        self.ml_enabled = True
        self.impairment: dict[str, Any] = {}
        # Timed comm faults (batch 2): tick at which each one lifts.
        self._link_impair_until: Optional[int] = None
        self._partition_zone: Optional[str] = None
        self._partition_until: int = 0

        if self.scenario.initial_burst:
            self._admit(self.task_gen.burst(0.0, self.scenario.initial_burst))

    # ==================================================================
    # public surface
    # ==================================================================
    @property
    def tick(self) -> int:
        return self.clock.tick

    @property
    def sim_time(self) -> float:
        return self.clock.sim_time

    @property
    def finished(self) -> bool:
        limit = self.scenario.duration_ticks
        return limit is not None and self.clock.tick >= limit

    @property
    def trace_hash(self) -> str:
        return self._hash.hexdigest()

    def set_policy(self, policy: CoordinationPolicy) -> None:
        """Swap the arbiter. Used to hand control from the stub to M4."""
        self.policy = policy

    def step(self) -> SimSnapshot:
        """Advance the simulation by exactly one tick and return the snapshot."""
        self.clock.begin()
        self._events_this_tick = []

        self._apply_due_injections()
        self._admit(self.task_gen.tick(self.sim_time, TICK_SECONDS))
        self._dispatch()
        self._plan()
        self._sync_comm_faults()

        states = self.observed_states()
        # Hand the arbiter this tick's ground-truth sightings, if it wants them.
        # Guarded with hasattr because the baseline policy is a different class
        # entirely and must not be forced to grow an integrity API it has no use
        # for - the comparison is only fair if the baseline stays the baseline.
        if hasattr(self.policy, "observe"):
            self.policy.observe(self.observations())
        self._advise(states)
        verdicts = self.policy.arbitrate(self.clock.tick, self.sim_time, states)
        self._apply_verdicts(verdicts)
        self._score_firewall(verdicts)
        # Enforce whatever the coordination layer has contained. Read back from
        # the policy rather than pushed by it, so the simulation remains the one
        # authority on robot state (law 1) and coordination cannot reach in.
        council = getattr(self.policy, "council", None)
        if council is not None:
            self.apply_containment(council.contained)
        # X-01. Same read-back discipline as containment, and for the same
        # reason: coordination judges, the simulation records.
        self._sync_sovereign()
        self._expire_blackouts()

        self._apply_onboard_brake()

        for rid in sorted(self.robots):
            self.robots[rid].step(TICK_SECONDS, self.rng, self.sensing)

        self._service()
        self._check_stalls()
        self._account_safety()
        self._update_hash()

        compute_ms = self.clock.end()

        snapshot = self._snapshot(compute_ms)
        self.clock.advance()
        return snapshot

    def run(self, ticks: Optional[int] = None) -> SimSnapshot:
        """Run headless for `ticks` (or until the scenario duration elapses).

        Returns the final snapshot. Used by the benchmark harness, which needs
        thousands of ticks as fast as the CPU allows rather than in real time.
        """
        limit = ticks if ticks is not None else self.scenario.duration_ticks
        if limit is None:
            raise ValueError("run() needs a tick count for an open-ended scenario")
        snapshot = self._snapshot(0.0)
        for _ in range(limit):
            snapshot = self.step()
        return snapshot

    def observed_states(self) -> dict[str, AMRState]:
        """What the world outside the simulation is allowed to see.

        Failed robots are omitted entirely: a dead agent stops transmitting,
        and its absence is precisely the signal the M4 failure detector (X-23)
        is built to act on. Handing out a state for a failed robot would let
        coordination cheat.
        """
        ts = self.clock.timestamp
        return {
            rid: r.to_amr_state(ts, reported=True)
            for rid, r in sorted(self.robots.items())
            if not r.failed
        }

    def true_states(self) -> dict[str, AMRState]:
        """Ground truth. Only the safety monitor and the scorer may use this."""
        ts = self.clock.timestamp
        return {
            rid: r.to_amr_state(ts, reported=False)
            for rid, r in sorted(self.robots.items())
        }

    def observations(self, *, radius_m: float = 12.0) -> dict:
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
                    # _release_task does the whole teardown - path, phase, goal
                    # cell, dwell, carried mass - and emits its own event. Only
                    # clearing current_task_id would leave a task assigned to a
                    # robot that will never move it, which is a slow leak of
                    # fleet capacity rather than a containment.
                    self._release_task(robot, reason="quarantined")
                events.append({"robot_id": rid, "action": "quarantine",
                               "task_released": released})
            elif not should and robot.quarantined:
                robot.quarantined = False
                robot.speed_scale = 1.0
                if not robot.failed:
                    robot.status = RobotStatus.AVAILABLE
                events.append({"robot_id": rid, "action": "release",
                               "task_released": None})
        for event in events:
            # _emit, not a direct append: the operator's event feed reads
            # self.events, and a containment that does not appear there is
            # invisible to the very person who has to judge it.
            self._emit("containment", **event)
        return events

    # ==================================================================
    # step 1 - faults
    # ==================================================================
    def _apply_due_injections(self) -> None:
        while (
            self._next_injection < len(self._injections)
            and self._injections[self._next_injection].at_tick <= self.clock.tick
        ):
            inj = self._injections[self._next_injection]
            self._next_injection += 1
            self.inject(inj.kind, **inj.params)

    def inject(self, kind: FaultKind | str, **params: Any) -> dict:
        """Apply a fault now. Callable live from the API for the demo."""
        kind = FaultKind(kind) if isinstance(kind, str) else kind
        handler = {
            FaultKind.ROBOT_FAILURE: self._fault_robot_failure,
            FaultKind.BATTERY_DRAIN: self._fault_battery_drain,
            FaultKind.BLOCK_AISLE: self._fault_block_aisle,
            FaultKind.CLEAR_BLOCKAGE: self._fault_clear_blockage,
            FaultKind.ROGUE_ROBOT: self._fault_rogue,
            FaultKind.LINK_IMPAIR: self._fault_link_impair,
            FaultKind.ZONE_PARTITION: self._fault_zone_partition,
            FaultKind.TASK_BURST: self._fault_task_burst,
            FaultKind.KILL_ML: self._fault_kill_ml,
            FaultKind.COMM_BLACKOUT: self._fault_comm_blackout,
        }[kind]
        detail = handler(**params)
        # fault_kind, not kind: "kind" is already the event-type field on every
        # emitted event, and shadowing it would collide.
        return self._emit("fault", fault_kind=kind.value, **detail)


    def _pick_robot(self, robot_id: Optional[str], *, healthy: bool = True) -> Optional[SimRobot]:
        """Resolve a robot id, or choose one deterministically from the RNG."""
        if robot_id is not None:
            return self.robots.get(robot_id)
        pool = [
            r for r in (self.robots[k] for k in sorted(self.robots))
            if (not r.failed) or (not healthy)
        ]
        if not pool:
            return None
        return self.rng.choice(pool)

    def _fault_robot_failure(self, robot_id: Optional[str] = None) -> dict:
        robot = self._pick_robot(robot_id)
        if robot is None:
            return {"applied": False, "reason": "no healthy robot"}
        robot.failed = True
        robot.status = RobotStatus.FAILED
        robot.velocity = 0.0
        robot.clear_path()
        # A corpse in an aisle is a new static obstacle, so every route that
        # runs through it is invalid as of this instant. Forcing the replan now
        # is the same honesty as _fault_block_aisle: a robot must not be left
        # driving at a wall just because the wall appeared late.
        self._invalidate_paths_near_failed()
        # The task it was carrying goes back on the queue. This is the piece
        # that makes recovery visible: throughput dips, then recovers.
        self._release_task(robot, reason="robot failed")
        return {"applied": True, "robot_id": robot.robot_id,
                "at_cell": self.warehouse.m_to_cell(robot.x, robot.y)}

    def _fault_battery_drain(
        self, robot_id: Optional[str] = None, level: float = 8.0, count: int = 1
    ) -> dict:
        drained: list[str] = []
        for _ in range(max(1, count)):
            robot = self._pick_robot(robot_id)
            if robot is None:
                break
            robot.battery = min(robot.battery, float(level))
            drained.append(robot.robot_id)
            if robot_id is not None:
                break
        return {"applied": bool(drained), "robots": drained, "level": level}

    def _fault_block_aisle(
        self, cx: Optional[int] = None, cy0: Optional[int] = None,
        cy1: Optional[int] = None,
    ) -> dict:
        if cx is None:
            cx = self.warehouse.width // 2
        if cy0 is None:
            cy0 = self.warehouse.height // 4
        if cy1 is None:
            cy1 = (self.warehouse.height * 3) // 4
        n = self.warehouse.block_aisle_segment(cx, cy0, cy1)
        # Any robot whose remaining path crosses a now-blocked cell must
        # replan. Forcing that here, rather than waiting for it to drive into
        # a wall, is the honest behaviour.
        invalidated = self._invalidate_paths_through_blockage()
        return {"applied": n > 0, "cells_blocked": n, "cx": cx,
                "cy0": cy0, "cy1": cy1, "paths_invalidated": invalidated}

    def _fault_clear_blockage(self) -> dict:
        n = self.warehouse.clear_blockage()
        return {"applied": n > 0, "cells_cleared": n}

    def _fault_rogue(self, robot_id: Optional[str] = None,
                     spoof_m: float = 2.5) -> dict:
        """Turn one robot into an adversary that lies about its position.

        The offset defaults to 2.5 m: well beyond the 1.5 m claim tolerance in
        app/coordination/integrity.py, so the lie is detectable, and beyond the
        0.70 m pair footprint, so it is genuinely dangerous - peers plan through
        the space the rogue actually occupies. A lie small enough to sit inside
        sensor noise would be neither.
        """
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

    def _fault_link_impair(
        self, drop_pct: float = 10.0, latency_ms: float = 40.0,
        jitter_ms: float = 20.0, ticks: int = COMM_FAULT_TICKS,
    ) -> dict:
        """Degrade the coordination radio fleet-wide for `ticks` ticks (X-02).

        Batch 2: this used to record the request and change nothing - the
        radio profile was never set, so the fault the Lab offered had no
        effect on behaviour. It now drives BoundedRadio.set_profile, whose
        loss draws come from the policy's own seeded RNG, so an impaired run is
        exactly as replayable as a clean one.

        Latency is modelled in whole ticks (100 ms at 10 Hz), rounded; a
        request below half a tick rounds to zero and is reported as such.
        Jitter is recorded but not modelled - the radio has no sub-tick clock.
        A policy without a radio (the stop-and-wait baseline) is unaffected,
        exactly as for COMM_BLACKOUT.
        """
        latency_ticks = int(round(float(latency_ms) / (1000.0 / TICK_HZ)))
        self.impairment = {
            "drop_pct": float(drop_pct),
            "latency_ms": float(latency_ms),
            "jitter_ms": float(jitter_ms),
            "latency_ticks": latency_ticks,
            "jitter_modelled": False,
        }
        radio = getattr(self.policy, "radio", None)
        if radio is None:
            self.impairment["applied_to_radio"] = False
            return {"applied": False, "reason": "policy has no radio", **self.impairment}
        radio.set_profile(LinkProfile(
            loss_pct=max(0.0, min(100.0, float(drop_pct))),
            latency_ticks=max(0, latency_ticks),
        ))
        self.impairment["applied_to_radio"] = True
        self._link_impair_until = self.clock.tick + max(1, int(ticks))
        return {"applied": True, "ticks": max(1, int(ticks)), **self.impairment}

    def _fault_zone_partition(self, zone: str = "EAST",
                              ticks: int = COMM_FAULT_TICKS) -> dict:
        """Cut radio links across the boundary of one zone for `ticks` ticks.

        Batch 2: like LINK_IMPAIR, this used to be recorded only. Membership is
        refreshed every tick by _sync_comm_faults, because robots drive in and
        out of the zone; links inside the zone and outside it are unaffected.
        """
        self.impairment = dict(self.impairment)
        self.impairment["partition_zone"] = zone
        radio = getattr(self.policy, "radio", None)
        if radio is None or not hasattr(radio, "set_partition"):
            self.impairment["partition_applied"] = False
            return {"applied": False, "reason": "policy has no radio", "zone": zone}
        if zone not in {z.name for z in self.warehouse.zones}:
            return {"applied": False, "reason": f"unknown zone {zone}", "zone": zone}
        self.impairment["partition_applied"] = True
        self._partition_zone = zone
        self._partition_until = self.clock.tick + max(1, int(ticks))
        self._sync_comm_faults()
        return {"applied": True, "zone": zone, "ticks": max(1, int(ticks))}

    def _sync_comm_faults(self) -> None:
        """Refresh the partition membership and expire timed comm faults.

        Called once per tick BEFORE arbitration, so the radio reflects this
        tick's positions when the policy broadcasts. Sorted iteration keeps the
        replay deterministic.
        """
        radio = getattr(self.policy, "radio", None)
        if radio is None:
            return
        tick = self.clock.tick
        if self._link_impair_until is not None and tick >= self._link_impair_until:
            radio.set_profile(LINK_PERFECT)
            self._link_impair_until = None
            for key in ("drop_pct", "latency_ms", "jitter_ms", "latency_ticks",
                        "jitter_modelled", "applied_to_radio"):
                self.impairment.pop(key, None)
            self._emit("impairment_ended", fault="LINK_IMPAIR")
        if self._partition_zone is not None:
            if tick >= self._partition_until:
                radio.set_partition(())
                self._emit("impairment_ended", fault="ZONE_PARTITION",
                           zone=self._partition_zone)
                self._partition_zone = None
                self.impairment.pop("partition_zone", None)
                self.impairment.pop("partition_applied", None)
            else:
                inside = [
                    rid for rid in sorted(self.robots)
                    if self.warehouse.zone_of(
                        *self.warehouse.m_to_cell(self.robots[rid].x, self.robots[rid].y)
                    ) == self._partition_zone
                ]
                radio.set_partition(inside)

    def _fault_task_burst(self, count: int = 20) -> dict:
        created = self.task_gen.burst(self.sim_time, int(count))
        self._admit(created)
        return {"applied": True, "count": len(created)}

    def _fault_kill_ml(self) -> dict:
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
                self._emit("sovereign", robot_id=rid, action="rejoin")

    # ==================================================================
    # steps 2 and 3 - tasks and dispatch
    # ==================================================================
    def _admit(self, created: list[Task]) -> None:
        for task in created:
            self.tasks[task.task_id] = task
            self.pending.append(task.task_id)
        if created:
            self._emit("tasks_created", count=len(created),
                       ids=[t.task_id for t in created])

    def _queue_order(self) -> list[str]:
        """Pending task ids, highest priority first, oldest first within a class.

        Sorting by (-weight, created_s, task_id) gives a total order, so the
        dispatch sequence never depends on dict iteration.
        """
        return sorted(
            self.pending,
            key=lambda tid: (
                -self.tasks[tid].priority.weight,
                self.tasks[tid].created_s,
                tid,
            ),
        )

    def _dispatch(self) -> None:
        """Greedy capability-gated assignment.

        This is the default allocator. When M4 is wired in, its auction
        replaces this method's choice of winner - but not its eligibility
        rules, which are physical facts about the robot and must be enforced
        here regardless of what any bidding scheme decides.
        """
        if not self.pending:
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

        free = [
            self.robots[rid] for rid in sorted(self.robots)
            if self.robots[rid].is_available_for_work
            and not self._held_after_stall(self.robots[rid])
        ]
        if not free:
            return

        for tid in self._queue_order():
            if not free:
                break
            task = self.tasks[tid]
            pick_m = self.warehouse.cell_to_m(*task.pick)

            best: Optional[SimRobot] = None
            best_cost = float("inf")

            for robot in free:
                # X-17 capability gate: a light robot physically cannot take a
                # heavy pallet, and no amount of eagerness in its bid changes
                # that.
                if not robot.spec.can_carry(task.payload_kg):
                    self.veto_capability += 1
                    continue

                # X-18 battery feasibility veto: refuse the job if finishing it
                # would take the robot below its reserve. Better to charge now
                # than to strand a loaded robot in an aisle.
                if not self._battery_feasible(robot, task):
                    self.veto_battery += 1
                    continue

                cost = robot.distance_to(*pick_m) / max(robot.spec.max_speed_mps, 1e-6)
                # Stable tie-break on id.
                if cost < best_cost - 1e-9 or (
                    abs(cost - best_cost) <= 1e-9
                    and best is not None
                    and robot.robot_id < best.robot_id
                ):
                    best, best_cost = robot, cost

            if best is None:
                continue

            task.status = TaskStatus.ASSIGNED
            task.assigned_robot = best.robot_id
            task.assigned_s = self.sim_time
            best.current_task_id = tid
            self._phase[best.robot_id] = "TO_PICK"
            self._goal_cell[best.robot_id] = task.pick
            self.pending.remove(tid)
            free.remove(best)
            self._emit("task_assigned", task_id=tid, robot_id=best.robot_id,
                       priority=task.priority.value, eta_s=round(best_cost, 2))

    def _held_after_stall(self, robot: SimRobot) -> bool:
        """Is this robot still in its post-stall re-dispatch hold?

        See STALL_CLEARANCE_M. The hold lifts as soon as the robot is clear of
        every other live robot, or after STALL_RELEASE_TICKS, whichever is
        first. Measured on true positions: dispatch is the engine's job and the
        engine is the authority on where robots are (law 1).
        """
        since = self._stall_hold.get(robot.robot_id)
        if since is None:
            return False
        if self.clock.tick - since >= STALL_RELEASE_TICKS:
            del self._stall_hold[robot.robot_id]
            return False
        for other in self.robots.values():
            if other is robot or other.failed:
                continue
            if robot.distance_to(other.x, other.y) < STALL_CLEARANCE_M:
                self.stall_holds_skipped += 1
                return True
        del self._stall_hold[robot.robot_id]
        return False

    def _battery_feasible(self, robot: SimRobot, task: Task) -> bool:
        """Would this robot still hold its reserve after finishing the task?

        Estimated conservatively with Manhattan distance and the move-drain
        rate. Conservative is correct here: an optimistic estimate strands
        robots, and a stranded loaded robot is the worst outcome in a real
        warehouse.
        """
        from app.sim.robot import MOVE_DRAIN_PCT_PER_S, PAYLOAD_DRAIN_PCT_PER_KG_S

        rc = self.warehouse.m_to_cell(robot.x, robot.y)
        legs = (
            abs(rc[0] - task.pick[0]) + abs(rc[1] - task.pick[1])
            + abs(task.pick[0] - task.drop[0]) + abs(task.pick[1] - task.drop[1])
        )
        seconds = legs / max(robot.spec.max_speed_mps, 1e-6)
        drain = seconds * (
            MOVE_DRAIN_PCT_PER_S + PAYLOAD_DRAIN_PCT_PER_KG_S * task.payload_kg
        )
        return (robot.battery - drain) >= BATTERY_RESERVE_PCT

    def _release_task(self, robot: SimRobot, *, reason: str) -> None:
        """Return a robot's task to the queue and clear its assignment."""
        tid = robot.current_task_id
        robot.current_task_id = None
        robot.carrying_kg = 0.0
        robot.clear_path()
        self._phase.pop(robot.robot_id, None)
        self._goal_cell.pop(robot.robot_id, None)
        self._dwell.pop(robot.robot_id, None)
        if tid is None:
            return
        task = self.tasks.get(tid)
        if task is None or task.status is TaskStatus.COMPLETE:
            return
        task.status = TaskStatus.PENDING
        task.assigned_robot = None
        task.assigned_s = None
        task.picked_s = None
        if tid not in self.pending:
            self.pending.append(tid)
        self._emit("task_released", task_id=tid, robot_id=robot.robot_id,
                   reason=reason)

    # ==================================================================
    # step 4 - planning
    # ==================================================================
    def _plan(self) -> None:
        avoid = self._failed_robot_cells()

        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if robot.failed or robot.status is RobotStatus.CHARGING:
                continue
            if robot.quarantined:
                # A contained robot gets no new path. Planning for it would
                # hand back the motion the containment just took away.
                continue
            if self._dwell.get(rid, 0) > 0:
                continue
            if robot.path:
                continue

            goal = self._goal_for(robot)
            if goal is None:
                continue

            start = self.warehouse.m_to_cell(robot.x, robot.y)
            start = nearest_navigable(self.warehouse, start) or start
            target = nearest_navigable(self.warehouse, goal)
            if target is None:
                continue

            # A hint is consumed whether or not it helps, so a robot can never
            # be permanently forbidden from a corridor by a stale grudge.
            hint = self._avoid_hint.pop(rid, set())
            detour = (avoid | hint) - {start, target}

            cells = find_path(self.warehouse, start, target, avoid=detour)
            if cells is None and hint:
                # The detour is infeasible - the hinted cell is the only way
                # through. Fall back to the plain route and let the arbiter keep
                # holding this robot until the blocker moves.
                cells = find_path(self.warehouse, start, target, avoid=avoid)
            if cells is None or len(cells) < 2:
                if cells is None:
                    # Genuinely unreachable right now. Say so rather than
                    # silently parking the robot forever.
                    self._emit("unreachable", robot_id=rid, goal=list(target))
                continue

            waypoints = simplify_collinear(path_to_metres(self.warehouse, cells))
            # Shared simulator fix, applied to EVERY policy alike: a robot
            # halted between two cell centres must not reverse to the centre
            # of the cell it is already leaving. See trim_passed_start.
            waypoints = trim_passed_start(waypoints, (robot.x, robot.y))
            self._intent_counter += 1
            robot.assign_path(
                waypoints,
                intent_id=f"I{self._intent_counter:07d}",
                target=self.warehouse.cell_to_m(*target),
            )
            # Telemetry (batch 2). Each plan is counted ONCE, here, and
            # classified: a REPLAN replaces a path that a verdict or an
            # invalidation took away; anything else is the INITIAL plan for a
            # new goal (task assigned, pick made, charger sought).
            self.path_plans += 1
            if rid in self._replan_due:
                self._replan_due.discard(rid)
                self.replans += 1
            else:
                self.initial_plans += 1

    def _goal_for(self, robot: SimRobot) -> Optional[tuple[int, int]]:
        """Where this robot should be heading next.

        Charging outranks work: a robot below reserve goes to a charger even if
        it is holding an assignment, because a dead robot in an aisle costs the
        fleet far more than one late task.
        """
        rid = robot.robot_id

        if robot.needs_charge and robot.current_task_id is None:
            self._phase[rid] = "TO_CHARGER"
            return self._nearest_charger(robot)

        phase = self._phase.get(rid)
        tid = robot.current_task_id

        if tid is not None and phase in ("TO_PICK", "TO_DROP"):
            task = self.tasks[tid]
            return task.pick if phase == "TO_PICK" else task.drop

        if phase == "TO_CHARGER":
            return self._nearest_charger(robot)

        return None

    def _nearest_charger(self, robot: SimRobot) -> Optional[tuple[int, int]]:
        if not self.charger_cells:
            return None
        # Manhattan is enough for selection and is cheaper than running A* to
        # every charger. Ties break on cell order for determinism.
        rc = self.warehouse.m_to_cell(robot.x, robot.y)
        return min(
            self.charger_cells,
            key=lambda c: (abs(c[0] - rc[0]) + abs(c[1] - rc[1]), c),
        )

    def _failed_robot_cells(self) -> set[tuple[int, int]]:
        """Cells occupied by dead robots, treated as static obstacles.

        This is the simulation half of X-23: a failed agent becomes a rock in
        the aisle that everyone else routes around.
        """
        return {
            self.warehouse.m_to_cell(r.x, r.y)
            for r in self.robots.values()
            if r.failed
        }

    def _invalidate_paths_near_failed(self) -> int:
        """Clear any path whose remaining waypoints run through a dead robot."""
        corpses = [
            (r.x, r.y) for r in self.robots.values() if r.failed
        ]
        if not corpses:
            return 0
        n = 0
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if robot.failed or not robot.path:
                continue
            for wx, wy in robot.path:
                if any(
                    math.hypot(wx - fx, wy - fy) <= ONBOARD_STOP_M
                    for fx, fy in corpses
                ):
                    robot.clear_path()
                    self._replan_due.add(rid)
                    self.path_invalidations += 1
                    n += 1
                    break
        return n

    def _apply_onboard_brake(self) -> None:
        """Physical last-resort proximity stop against non-transmitting hazards.

        This is NOT a second coordination layer, and it deliberately cannot
        rescue a bad policy: it only ever considers FAILED robots, which are
        exactly the obstacles the arbiter provably cannot reason about, because
        observed_states() withholds them (a dead agent stops transmitting, and
        that silence is the X-23 trigger). Every hazard a policy can actually
        see is still entirely the policy's responsibility, so the unarbitrated
        negative control still collides and the zero-collision result stays a
        real measurement rather than an artefact of this brake.

        It models the bumper and LiDAR emergency stop that every real AMR has
        in hardware, below and independent of any fleet software. Without it
        the simulation would assert something false: that a robot happily
        drives through a stationary machine merely because the radio went
        quiet.
        """
        hazards = [r for r in self.robots.values() if r.failed]
        if not hazards:
            return

        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if robot.failed or robot.speed_scale <= 0.0:
                continue
            step = robot.velocity * TICK_SECONDS + 0.25
            for hazard in hazards:
                if robot.distance_to(hazard.x, hazard.y) <= ONBOARD_STOP_M + step:
                    robot.apply_verdict_scale(0.0)
                    robot.status = RobotStatus.BLOCKED
                    break

    def _invalidate_paths_through_blockage(self) -> int:
        """Clear any path that now crosses a blocked cell. Returns the count."""
        n = 0
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if not robot.path:
                continue
            for wx, wy in robot.path:
                if not self.warehouse.is_navigable(*self.warehouse.m_to_cell(wx, wy)):
                    robot.clear_path()
                    self._replan_due.add(rid)
                    self.path_invalidations += 1
                    n += 1
                    break
        return n

    # ==================================================================
    # step 4b - advisory layer (M3). Never in the safety path.

    def _advise(self, states: dict) -> None:
        """Ask the ML layer for proposals. Failures here are swallowed.

        An advisory layer that can crash the simulator is in the safety path by
        accident, which is exactly the coupling law 3 forbids. If the forecaster
        raises we drop its proposals for the tick, record nothing, and carry on;
        the robots never notice.
        """
        if not self.ml_enabled:
            self._last_advisories = {}
            return
        try:
            self.forecaster.observe(list(states.values()), self.clock.tick)
            self._last_advisories = self.forecaster.advise(list(states.values()))
        except Exception as exc:
            # Counted, not hidden. An uncounted swallow let a forecaster that
            # crashed on every single tick read as "no congestion detected",
            # which is the worst possible failure mode for an instrument: it
            # looks like good news.
            self.ml_errors += 1
            self.ml_last_error = f"{type(exc).__name__}: {exc}"
            self._last_advisories = {}

    def _score_firewall(self, verdicts: dict) -> None:
        """Count how often the binding kernel disagreed with the proposal.

        A robot with no proposal is neither an agreement nor an override.
        Counting silence as agreement would drive the agreement rate to ~100%
        and the number would stop meaning anything.
        """
        for rid, adv in self._last_advisories.items():
            binding = verdicts.get(rid)
            bound_kind = binding.kind.value if binding is not None else VerdictKind.PROCEED.value
            self.advisories_proposed += 1
            if adv.kind == bound_kind:
                self.advisories_agreed += 1
            else:
                self.advisories_overridden += 1
                key = f"{adv.kind}->{bound_kind}"
                self._override_pairs[key] = self._override_pairs.get(key, 0) + 1

    def advisory_stats(self) -> dict:
        """The law-3 evidence, in the shape the Analytics panel renders."""
        total = self.advisories_proposed
        top = sorted(self._override_pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        return {
            "ml_enabled": self.ml_enabled,
            "proposed": total,
            "agreed": self.advisories_agreed,
            "overridden": self.advisories_overridden,
            "override_pct": round(self.advisories_overridden / total * 100.0, 1)
            if total
            else None,
            "top_overrides": dict(top),
            "forecast_accuracy": self.forecaster.accuracy(),
            "errors": self.ml_errors,
            "last_error": self.ml_last_error,
        }

    # step 5 - verdicts
    # ==================================================================
    def _apply_verdicts(self, verdicts: dict[str, Verdict]) -> None:
        self._last_verdicts = verdicts
        for rid, verdict in verdicts.items():
            robot = self.robots.get(rid)
            if robot is None or robot.failed:
                continue
            self.verdict_counts[verdict.kind.value] += 1
            robot.apply_verdict_scale(verdict.speed_scale or 0.0)
            if verdict.needs_replan and robot.path:
                # The arbiter has declared the current path invalid. Dropping
                # it here means the next _plan() rebuilds it; the robot holds
                # position for at most one tick.
                robot.clear_path()
                self._replan_due.add(rid)
                self.path_invalidations += 1
                # Carry the reason for the reroute into the replan, so the new
                # path actually differs from the one that just failed.
                hint = {
                    self.warehouse.m_to_cell(peer.x, peer.y)
                    for peer in (self.robots.get(p) for p in verdict.conflict_with)
                    if peer is not None
                }
                if hint:
                    self._avoid_hint[rid] = hint

        # Robots the policy said nothing about default to full speed rather
        # than to a stall, but that is a bug in the policy, so it is recorded.
        for rid, robot in self.robots.items():
            if rid not in verdicts and not robot.failed:
                robot.apply_verdict_scale(1.0)

    # ==================================================================
    # steps 6 and 7 - service
    # ==================================================================
    def _service(self) -> None:
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if robot.failed:
                continue

            if self._dwell.get(rid, 0) > 0:
                self._dwell[rid] -= 1
                continue

            phase = self._phase.get(rid)

            if phase == "TO_CHARGER":
                goal = self._nearest_charger(robot)
                if goal is not None and self._at_cell(robot, goal):
                    robot.status = RobotStatus.CHARGING
                    self._phase.pop(rid, None)
                    self._emit("charging_started", robot_id=rid,
                               battery=round(robot.battery, 1))
                continue

            tid = robot.current_task_id
            if tid is None:
                continue
            task = self.tasks[tid]

            if phase == "TO_PICK" and self._at_cell(robot, task.pick):
                task.status = TaskStatus.CARRYING
                task.picked_s = self.sim_time
                robot.carrying_kg = task.payload_kg
                self._phase[rid] = "TO_DROP"
                self._goal_cell[rid] = task.drop
                self._dwell[rid] = DWELL_TICKS
                robot.clear_path()
                self._emit("task_picked", task_id=tid, robot_id=rid)

            elif phase == "TO_DROP" and self._at_cell(robot, task.drop):
                task.status = TaskStatus.COMPLETE
                task.completed_s = self.sim_time
                robot.carrying_kg = 0.0
                robot.current_task_id = None
                robot.tasks_completed += 1
                robot.status = RobotStatus.AVAILABLE
                self._phase.pop(rid, None)
                self._goal_cell.pop(rid, None)
                self._dwell[rid] = DWELL_TICKS
                robot.clear_path()
                self.completed.append(tid)
                self._emit(
                    "task_complete", task_id=tid, robot_id=rid,
                    completion_s=round(task.completion_time_s or 0.0, 2),
                    late=task.is_late(self.sim_time),
                )

    def _at_cell(self, robot: SimRobot, cell: tuple[int, int]) -> bool:
        cx, cy = self.warehouse.cell_to_m(*cell)
        return robot.distance_to(cx, cy) <= SERVICE_RADIUS_M

    _COORDINATION_KEYS = (
        "contests", "repeated_contests", "feasibility_swaps", "headon_replans",
        "stuck_yield_replans", "stuck_yield_detections", "yields_total", "yields_winner_held",
        "winner_held_pct", "monitor_vetoes", "perception_blocks", "reroutes",
        "failures_confirmed",
    )

    def _coordination_stats(self) -> dict:
        stats_fn = getattr(self.policy, "stats", None)
        if stats_fn is None:
            return {}
        stats = stats_fn()
        return {k: stats[k] for k in self._COORDINATION_KEYS if k in stats}

    def _stalled_count(self) -> int:
        tick = self.clock.tick
        return sum(
            1 for rid, (since, _x, _y) in self._stall.items()
            if tick - since >= STALL_REPORT_TICKS
            and self._dwell.get(rid, 0) == 0
            and self.robots[rid].current_task_id is not None
        )

    def _check_stalls(self) -> None:
        """Release a task whose robot has made no measurable progress.

        See STALL_RELEASE_TICKS above for the full reasoning. This runs after
        motion has been integrated for the tick, so `robot.x, robot.y` are
        this tick's TRUE final position - exactly what should be compared
        against the position last recorded for this robot.

        Only robots that currently hold a task and are not already resting
        for a legitimate reason (dwell, charging, quarantine, failure) are
        tracked, so a robot that is correctly idle between tasks is never
        mistaken for one that is wedged.
        """
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            if robot.current_task_id is None or robot.failed or robot.quarantined:
                self._stall.pop(rid, None)
                continue
            if self._dwell.get(rid, 0) > 0:
                # Dwelling at a pick/drop station is real, intended rest, not
                # a stall - reset the clock so it does not fire the instant
                # dwell ends.
                self._stall[rid] = (self.clock.tick, robot.x, robot.y)
                continue

            prev = self._stall.get(rid)
            if prev is None:
                self._stall[rid] = (self.clock.tick, robot.x, robot.y)
                continue

            since_tick, px, py = prev
            moved = math.hypot(robot.x - px, robot.y - py)
            if moved >= STALL_EPS_M:
                self._stall[rid] = (self.clock.tick, robot.x, robot.y)
                continue

            if self.clock.tick - since_tick >= STALL_RELEASE_TICKS:
                self.stall_releases += 1
                self._emit(
                    "task_stalled", robot_id=rid, task_id=robot.current_task_id,
                    ticks_without_progress=self.clock.tick - since_tick,
                )
                self._release_task(robot, reason="no progress for %d ticks" % STALL_RELEASE_TICKS)
                robot.status = RobotStatus.AVAILABLE
                self._stall.pop(rid, None)
                self._stall_hold[rid] = self.clock.tick

    # ==================================================================
    # step 8 - safety accounting and hashing
    # ==================================================================

    def _account_safety(self) -> None:
        """Count space-time overlaps on TRUE positions. This is X-09.

        Uniform-grid broad phase so the check stays O(N) rather than O(N^2);
        at 100 robots the naive version would burn a measurable slice of the
        100 ms tick budget, and the safety monitor must never be the thing
        that makes us miss real time.
        """
        buckets: dict[tuple[int, int], list[SimRobot]] = {}
        cell = NEAR_MISS_DISTANCE_M
        for rid in sorted(self.robots):
            robot = self.robots[rid]
            key = (int(robot.x // cell), int(robot.y // cell))
            buckets.setdefault(key, []).append(robot)

        seen: set[tuple[str, str]] = set()
        # Pairs seen this tick that are overlapping or merely near.
        # Anything in self._overlapping but absent from these has moved
        # fully apart and is re-armed at the bottom of this method.
        still_close: set[tuple[str, str]] = set()
        for (bx, by), members in buckets.items():
            candidates: list[SimRobot] = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    candidates.extend(buckets.get((bx + dx, by + dy), ()))
            for a in members:
                for b in candidates:
                    if a.robot_id >= b.robot_id:
                        continue
                    pair = (a.robot_id, b.robot_id)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    d = a.distance_to(b.x, b.y)
                    if d < COLLISION_DISTANCE_M:
                        self.overlap_ticks += 1
                        # Edge-triggered. Only the tick on which the pair first
                        # closes inside the threshold is a collision; the ticks
                        # it then spends overlapping are dwell, counted above.
                        still_close.add(pair)
                        if pair not in self._overlapping:
                            self._overlapping.add(pair)
                            self.violations.append(
                                Violation(self.clock.tick, self.sim_time,
                                          a.robot_id, b.robot_id, d)
                            )
                            self._emit("safety_violation", robot_a=a.robot_id,
                                       robot_b=b.robot_id, distance_m=round(d, 4))
                    elif d < NEAR_MISS_DISTANCE_M:
                        self.near_misses += 1
                        still_close.add(pair)
                    else:
                        # Fully separated, so the pair may be counted again if
                        # it ever closes a second time. Re-arming at the
                        # near-miss distance rather than the collision distance
                        # gives hysteresis: a pair sitting exactly on the
                        # 0.70 m boundary cannot ratchet the count up on float
                        # noise alone.
                        pass

        # Pairs that have separated beyond the near-miss ring are
        # forgotten, so a genuinely new approach later in the run is
        # counted as a new collision rather than being suppressed.
        self._overlapping &= still_close

    def _update_hash(self) -> None:
        """Fold this tick into the rolling trace hash (X-22).

        Quantised to millimetres before hashing. Without quantisation the hash
        would be hostage to the last bit of float arithmetic, which differs
        across CPUs and Python builds and would make the determinism claim
        fail for the wrong reason.
        """
        parts = [str(self.clock.tick)]
        for rid in sorted(self.robots):
            r = self.robots[rid]
            parts.append(
                f"{rid}:{int(round(r.x * 1000))}:{int(round(r.y * 1000))}"
                f":{r.status.value}:{r.current_task_id or '-'}"
            )
        parts.append(f"done={len(self.completed)}")
        parts.append(f"viol={len(self.violations)}")
        self._hash.update("|".join(parts).encode())

    # ==================================================================
    # reporting
    # ==================================================================
    def _emit(self, kind: str, **fields: Any) -> dict:
        event = {"tick": self.clock.tick, "sim_time": round(self.sim_time, 2),
                 "kind": kind, **fields}
        self._events_this_tick.append(event)
        self.events.append(event)
        # Bounded history: the full record belongs in the M6 trace file, not
        # in the engine's memory.
        if len(self.events) > 5000:
            del self.events[:1000]
        return event

    def _integrity_stats(self):
        """The coordination layer's integrity block, or None when it is off.

        None rather than a dict of zeros: the operator must be able to tell
        "nothing was rejected" apart from "nothing was watching". A zero in
        place of an unknown is the one kind of lie this dashboard cannot tell,
        since the entire feature it describes is about detecting lies.
        """
        stats = getattr(self.policy, "stats", None)
        if not callable(stats):
            return None
        block = stats().get("integrity")
        if not isinstance(block, dict) or not block.get("enabled"):
            return None
        return block

    def kpis(self, compute_ms: float = 0.0) -> dict:
        """Everything the command centre and the benchmark report need.

        Deliberately one method, so the number on screen and the number in the
        report cannot drift apart.
        """
        done = [self.tasks[t] for t in self.completed]
        times = [t.completion_time_s for t in done if t.completion_time_s is not None]
        waits = [t.wait_time_s for t in done if t.wait_time_s is not None]
        late = sum(1 for t in done if t.completed_s is not None
                   and t.completed_s > t.deadline_s)

        elapsed_min = self.sim_time / 60.0
        active = sum(
            1 for r in self.robots.values()
            if r.current_task_id is not None and not r.failed
        )

        return {
            "label": self.label,
            "policy": self.policy.name,
            "tick": self.clock.tick,
            "sim_time_s": round(self.sim_time, 2),
            # headline
            "tasks_per_min": round(len(done) / elapsed_min, 2) if elapsed_min > 0 else 0.0,
            "tasks_complete": len(done),
            "tasks_pending": len(self.pending),
            "tasks_active": active,
            # the >=20% criterion
            "avg_completion_s": round(sum(times) / len(times), 2) if times else None,
            "p95_completion_s": _pct(times, 0.95),
            "avg_wait_s": round(sum(waits) / len(waits), 2) if waits else None,
            # the zero-collision criterion
            "collisions": len(self.violations),
            # Pair-ticks spent inside the collision threshold. Reported
            # alongside the event count so a single frozen overlap is visibly
            # distinguishable from many brief ones.
            "overlap_ticks": self.overlap_ticks,
            "near_misses": self.near_misses,
            # SLA
            "sla_misses": late,
            "sla_miss_pct": round(100.0 * late / len(done), 1) if done else 0.0,
            # coordination behaviour
            "verdicts": dict(self.verdict_counts),
            "replans": self.replans,
            "initial_plans": self.initial_plans,
            "path_plans": self.path_plans,
            "path_invalidations": self.path_invalidations,
            # Robots holding a task that have made no measurable progress for
            # at least STALL_REPORT_TICKS (not counting pick/drop dwell).
            "robots_stalled": self._stalled_count(),
            # Batch 2: the arbiter's own coordination counters, when it has
            # them (the stop-and-wait baseline does not). Read-only telemetry.
            "coordination": self._coordination_stats(),
            "stall_releases": self.stall_releases,
            "veto_battery": self.veto_battery,
            "veto_capability": self.veto_capability,

            # fleet health
            "robots_total": len(self.robots),
            "robots_failed": sum(1 for r in self.robots.values() if r.failed),
            "robots_charging": sum(
                1 for r in self.robots.values() if r.status is RobotStatus.CHARGING
            ),
            "robots_rogue": sum(1 for r in self.robots.values() if r.rogue),
            # X-01. Beside robots_rogue and not folded into it: a robot with a
            # dead radio and a robot telling lies are different problems with
            # different operator responses.
            "robots_sovereign": sum(
                1 for r in self.robots.values() if r.sovereign
            ),
            "avg_battery": round(
                sum(r.battery for r in self.robots.values()) / max(1, len(self.robots)), 1
            ),
            # real-time budget (X-04)
            "compute_ms": round(compute_ms, 3),
            "advisory": self.advisory_stats(),
            "integrity": self._integrity_stats(),
            "compute": self.clock.compute_stats(),
            "ml_enabled": self.ml_enabled,
            "impairment": dict(self.impairment),
        }

    def _snapshot(self, compute_ms: float) -> SimSnapshot:
        return SimSnapshot(
            tick=self.clock.tick,
            sim_time=self.sim_time,
            timestamp=self.clock.timestamp,
            robots=[self.robots[rid].as_render_dict() for rid in sorted(self.robots)],
            verdicts=self._verdict_payload(),
            tasks_pending=len(self.pending),
            tasks_active=sum(
                1 for r in self.robots.values() if r.current_task_id is not None
            ),
            tasks_complete=len(self.completed),
            kpis=self.kpis(compute_ms),
            events=list(self._events_this_tick),
            trace_hash=self.trace_hash,
        )

    def _verdict_payload(self) -> list[dict]:
        """Verdict dicts for the wire, each carrying the advisory that was
        proposed for that robot (or None).

        The advisory is attached here, at the display boundary, and nowhere
        else. Nothing upstream of this method has read it.
        """
        out: list[dict] = []
        emitted: set[str] = set()
        for rid in sorted(self._last_verdicts):
            verdict = self._last_verdicts[rid]
            adv = self._last_advisories.get(rid)
            # PROCEED is normally omitted - a frame carrying a PROCEED for every
            # unconstrained robot is mostly noise. But a PROCEED that REJECTED
            # an advisory is the opposite of noise: it is the single clearest
            # demonstration that the kernel decides independently, and it is the
            # most common override we measure. Those are kept.
            if verdict.kind is VerdictKind.PROCEED and adv is None:
                continue
            row = verdict.as_dict()
            row["advisory"] = adv.as_dict() if adv is not None else None
            out.append(row)
            emitted.add(rid)

        # A robot the ML layer had an opinion about that the kernel did not
        # rule on at all is still an override, and it must be visible. Without
        # this the Inspector could only ever show advisories the kernel agreed
        # with, which would misrepresent the firewall as a rubber stamp.
        for rid in sorted(self._last_advisories):
            if rid in emitted:
                continue
            adv = self._last_advisories[rid]
            out.append(
                {
                    "robot_id": rid,
                    "kind": VerdictKind.PROCEED.value,
                    "reason": (
                        "No constraint applied. The kernel found no conflict "
                        "and let this robot run at full speed."
                    ),
                    "speed_scale": 1.0,
                    "yield_to": None,
                    "conflict_with": [],
                    "utility_terms": {},
                    "winning_margin": None,
                    "needs_replan": False,
                    "advisory": adv.as_dict(),
                }
            )
        return out

    def static_payload(self) -> dict:
        """Geometry plus fleet specs. Sent once on websocket connect."""
        return {
            "scenario": self.scenario.as_dict(),
            "seed": self.seed,
            "tick_hz": TICK_HZ,
            "warehouse": self.warehouse.to_render_payload(),
            "fleet": {
                rid: self.robots[rid].spec.as_dict() for rid in sorted(self.robots)
            },
            "collision_distance_m": COLLISION_DISTANCE_M,
        }


def _pct(values: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile. Returns None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return round(ordered[idx], 2)

# File contains AI-generated response based on internal company sources
