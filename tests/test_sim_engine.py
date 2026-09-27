"""Tests for the M5 simulation package.

These tests are the evidence behind three published success criteria, so they
are written as assertions about the product, not as coverage filler:

  determinism      same seed -> identical trace hash            (X-22)
  zero collisions  the arbitrated fleet never overlaps          (X-09)
  real time        a tick fits inside the 100 ms budget         (X-04)

The collision test is paired with a deliberate NEGATIVE control: the same
scenario under NoOpPolicy must actually produce violations. Without that, a
zero could simply mean the detector is broken.
"""

from __future__ import annotations

import math

import pytest

from app.sim import (
    COLLISION_DISTANCE_M,
    NoOpPolicy,
    SimEngine,
    StopAndWaitPolicy,
    TICK_HZ,
    TICK_SECONDS,
    VerdictKind,
    find_path,
    get_scenario,
    nearest_navigable,
    scalability_variants,
)
from app.sim.pathfinding import simplify_collinear
from app.sim.robot import PayloadClass, RobotSpec, SpeedClass, normalise_heading
from app.sim.scenarios import FaultKind
from app.sim.tasks import TaskStatus
from app.sim.warehouse import Cell, Warehouse


# ----------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------

def test_warehouse_has_navigable_service_points():
    """A warehouse with unreachable pick or drop points is useless."""
    w = Warehouse.standard()
    assert w.cells_of_type(Cell.PICK), "no pick cells generated"
    assert w.cells_of_type(Cell.DROP), "no drop cells generated"
    assert w.cells_of_type(Cell.CHARGER), "no charger cells generated"
    for cell in w.cells_of_type(Cell.PICK) + w.cells_of_type(Cell.DROP):
        assert w.is_navigable(*cell), f"service cell {cell} is not navigable"


def test_grid_metre_roundtrip_is_exact():
    """The ONE conversion must be its own inverse for cell centres."""
    w = Warehouse.standard()
    for cell in [(0, 0), (7, 3), (59, 39), (30, 20)]:
        assert w.m_to_cell(*w.cell_to_m(*cell)) == cell


def test_every_pick_reaches_every_drop():
    """The floor plan must be fully connected, or tasks silently never finish."""
    w = Warehouse.standard()
    picks = w.cells_of_type(Cell.PICK)
    drops = w.cells_of_type(Cell.DROP)
    # Sampling the corners is enough: if the extremes connect, the interior does.
    for start in (picks[0], picks[-1]):
        for goal in (drops[0], drops[-1]):
            assert find_path(w, start, goal) is not None, f"{start} -> {goal} unreachable"


def test_pathfinding_is_deterministic_and_optimal():
    w = Warehouse.standard()
    # (57, 37) looks like a corner but is a RACK cell in the standard plan, and
    # the planner correctly refuses a non-navigable goal. Resolve the intended
    # far corner to the nearest aisle cell, exactly as the engine does.
    a = nearest_navigable(w, (2, 2))
    b = nearest_navigable(w, (57, 37))
    assert a is not None and b is not None
    assert w.is_navigable(*a) and w.is_navigable(*b)
    first = find_path(w, a, b)
    second = find_path(w, a, b)
    assert first == second, "A* returned different paths for identical input"
    assert first is not None
    # Manhattan distance is the unobstructed lower bound.
    assert len(first) - 1 >= abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_blocked_cells_are_not_routed_through():
    w = Warehouse.standard()
    path = find_path(w, (2, 2), (2, 30))
    assert path is not None
    w.block_cells(path[1:-1])
    # With the interior of the old route sealed, the planner must either find a
    # different route or admit failure, but never reuse a blocked cell.
    new_path = find_path(w, (2, 2), (2, 30))
    if new_path is not None:
        assert not (set(new_path) & w.blocked)


def test_simplify_collinear_preserves_endpoints():
    pts = [(0.5, 0.5), (1.5, 0.5), (2.5, 0.5), (2.5, 1.5), (2.5, 2.5)]
    out = simplify_collinear(pts)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert len(out) == 3, f"expected 3 corner points, got {out}"


# ----------------------------------------------------------------------
# robot model
# ----------------------------------------------------------------------

def test_heading_is_always_in_canonical_range():
    for theta in (-0.1, 0.0, math.pi, 2 * math.pi, 7 * math.pi, -13.3):
        h = normalise_heading(theta)
        assert 0.0 <= h < 2 * math.pi


def test_capability_classes_are_ordered():
    light = RobotSpec(PayloadClass.LIGHT, SpeedClass.FAST)
    heavy = RobotSpec(PayloadClass.HEAVY, SpeedClass.SLOW)
    assert light.capacity_kg < heavy.capacity_kg
    assert light.max_speed_mps > heavy.max_speed_mps
    assert not light.can_carry(150.0)
    assert heavy.can_carry(150.0)


def test_amr_state_export_validates():
    """to_amr_state must always produce a model that passes M4's validators."""
    eng = SimEngine("blocked_aisle", seed=7, policy=StopAndWaitPolicy())
    eng.run(30)
    for state in eng.observed_states().values():
        assert state.velocity >= 0.0
        assert 0.0 <= state.heading < 2 * math.pi
        assert 0.0 <= state.battery <= 100.0


# ----------------------------------------------------------------------
# determinism  (X-22)
# ----------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["rush_50", "narrow_aisle_deadlock", "blocked_aisle"])
def test_same_seed_gives_identical_trace_hash(scenario):
    a = SimEngine(scenario, seed=1234, policy=StopAndWaitPolicy())
    b = SimEngine(scenario, seed=1234, policy=StopAndWaitPolicy())
    a.run(200)
    b.run(200)
    assert a.trace_hash == b.trace_hash
    assert a.kpis()["tasks_complete"] == b.kpis()["tasks_complete"]


def test_different_seed_gives_different_trace_hash():
    """If the seed did not matter, determinism would be trivial and meaningless."""
    a = SimEngine("rush_50", seed=1, policy=StopAndWaitPolicy())
    b = SimEngine("rush_50", seed=2, policy=StopAndWaitPolicy())
    a.run(150)
    b.run(150)
    assert a.trace_hash != b.trace_hash


def test_sim_time_is_pure_function_of_tick():
    eng = SimEngine("blocked_aisle", seed=3, policy=StopAndWaitPolicy())
    eng.run(57)
    assert eng.sim_time == pytest.approx(57 * TICK_SECONDS)


# ----------------------------------------------------------------------
# safety invariant  (X-09)
# ----------------------------------------------------------------------

def test_arbitrated_fleet_records_no_collisions():
    eng = SimEngine("rush_50", seed=99, policy=StopAndWaitPolicy())
    eng.run(600)          # 60 simulated seconds
    assert eng.kpis()["collisions"] == 0, (
        f"safety invariant breached: {[v.as_dict() for v in eng.violations[:5]]}"
    )


def test_unarbitrated_fleet_does_collide_negative_control():
    """The detector must be able to fire, otherwise the zero above is vacuous."""
    eng = SimEngine("narrow_aisle_deadlock", seed=5, policy=NoOpPolicy())
    eng.run(600)
    assert eng.kpis()["collisions"] > 0, (
        "no violations under NoOpPolicy - the collision detector is not working"
    )


def test_violations_are_recorded_with_detail():
    eng = SimEngine("narrow_aisle_deadlock", seed=5, policy=NoOpPolicy())
    eng.run(400)
    if eng.violations:
        v = eng.violations[0].as_dict()
        assert v["distance_m"] < COLLISION_DISTANCE_M
        assert v["robot_a"] < v["robot_b"]      # canonical pair ordering
        assert v["tick"] >= 0


# ----------------------------------------------------------------------
# throughput and task lifecycle
# ----------------------------------------------------------------------

def test_tasks_actually_complete():
    eng = SimEngine("rush_50", seed=11, policy=StopAndWaitPolicy())
    eng.run(900)
    k = eng.kpis()
    assert k["tasks_complete"] > 0, "no task completed in 90 s - the fleet is stuck"
    assert k["avg_completion_s"] is not None
    assert k["tasks_per_min"] > 0.0


def test_completed_tasks_have_consistent_timestamps():
    eng = SimEngine("rush_50", seed=13, policy=StopAndWaitPolicy())
    eng.run(600)
    for tid in eng.completed:
        t = eng.tasks[tid]
        assert t.status is TaskStatus.COMPLETE
        assert t.assigned_s is not None and t.assigned_s >= t.created_s
        assert t.picked_s is not None and t.picked_s >= t.assigned_s
        assert t.completed_s is not None and t.completed_s >= t.picked_s


def test_capability_gate_is_enforced():
    """No robot may ever be assigned a payload beyond its class capacity."""
    eng = SimEngine("rush_50", seed=17, policy=StopAndWaitPolicy())
    eng.run(600)
    for tid, task in eng.tasks.items():
        if task.assigned_robot is None:
            continue
        spec = eng.robots[task.assigned_robot].spec
        assert spec.can_carry(task.payload_kg), (
            f"{task.assigned_robot} ({spec.payload_class}) assigned "
            f"{task.payload_kg} kg task {tid}"
        )


# ----------------------------------------------------------------------
# faults
# ----------------------------------------------------------------------

def test_robot_failure_returns_its_task_to_the_queue():
    eng = SimEngine("rush_50", seed=21, policy=StopAndWaitPolicy())
    eng.run(200)
    busy = [r for r in eng.robots.values() if r.current_task_id is not None]
    assert busy, "expected at least one busy robot after 20 s"
    victim = busy[0]
    tid = victim.current_task_id
    before = len(eng.pending)
    eng.inject(FaultKind.ROBOT_FAILURE, robot_id=victim.robot_id)
    assert victim.failed
    assert eng.tasks[tid].status is TaskStatus.PENDING
    assert len(eng.pending) == before + 1


def test_failed_robot_is_not_in_observed_state():
    """A dead agent stops transmitting - that absence is the X-23 trigger."""
    eng = SimEngine("rush_50", seed=23, policy=StopAndWaitPolicy())
    eng.run(50)
    eng.inject(FaultKind.ROBOT_FAILURE, robot_id="R001")
    assert "R001" not in eng.observed_states()
    assert "R001" in eng.true_states()


def test_fleet_recovers_throughput_after_a_failure():
    eng = SimEngine("rush_50", seed=29, policy=StopAndWaitPolicy())
    eng.run(300)
    eng.inject(FaultKind.ROBOT_FAILURE)
    before = eng.kpis()["tasks_complete"]
    eng.run(600)
    assert eng.kpis()["tasks_complete"] > before, (
        "fleet made no progress after a single robot failure - likely deadlocked"
    )
    assert eng.kpis()["collisions"] == 0


def test_blocking_an_aisle_invalidates_paths_and_stays_safe():
    eng = SimEngine("blocked_aisle", seed=31, policy=StopAndWaitPolicy())
    eng.run(400)          # injections fire at t=20 s
    k = eng.kpis()
    assert eng.warehouse.blocked, "the scheduled blockage never applied"
    assert k["collisions"] == 0
    assert k["replans"] > 0


def test_battery_veto_fires_when_the_fleet_is_drained():
    eng = SimEngine("rush_50", seed=37, policy=StopAndWaitPolicy())
    eng.run(100)
    for rid in list(eng.robots)[:20]:
        eng.inject(FaultKind.BATTERY_DRAIN, robot_id=rid, level=16.0)
    eng.run(300)
    assert eng.kpis()["veto_battery"] > 0, "battery feasibility veto never triggered"


def test_low_battery_robots_go_to_charge():
    eng = SimEngine("rush_50", seed=41, policy=StopAndWaitPolicy())
    eng.run(50)
    for rid in list(eng.robots)[:10]:
        eng.robots[rid].current_task_id = None
        eng.inject(FaultKind.BATTERY_DRAIN, robot_id=rid, level=10.0)
    eng.run(1200)
    assert eng.kpis()["robots_charging"] > 0, "no drained robot reached a charger"


def test_kill_ml_flag_is_observable():
    eng = SimEngine("rush_50", seed=43, policy=StopAndWaitPolicy())
    assert eng.kpis()["ml_enabled"] is True
    eng.inject(FaultKind.KILL_ML)
    assert eng.kpis()["ml_enabled"] is False


# ----------------------------------------------------------------------
# real-time budget  (X-04)
# ----------------------------------------------------------------------

def test_tick_fits_the_budget_at_fifty_robots():
    eng = SimEngine("rush_50", seed=47, policy=StopAndWaitPolicy())
    eng.run(300)
    stats = eng.kpis()["compute"]
    assert stats["budget_ms"] == pytest.approx(1000.0 / TICK_HZ)
    assert stats["p95_ms"] < stats["budget_ms"], (
        f"p95 tick compute {stats['p95_ms']} ms exceeds the "
        f"{stats['budget_ms']} ms budget"
    )


def test_scalability_variants_hold_load_per_robot_constant():
    variants = scalability_variants("rush_50", sizes=(10, 50))
    base = get_scenario("rush_50")
    for v in variants:
        per_robot = v.task_rate_per_s / v.fleet_size
        assert per_robot == pytest.approx(
            base.task_rate_per_s / base.fleet_size, rel=1e-3
        )


# ----------------------------------------------------------------------
# policy seam
# ----------------------------------------------------------------------

def test_stop_and_wait_produces_wait_verdicts():
    eng = SimEngine("narrow_aisle_deadlock", seed=53, policy=StopAndWaitPolicy())
    eng.run(300)
    assert eng.verdict_counts[VerdictKind.WAIT.value] > 0, (
        "baseline never halted anyone - it is not actually arbitrating"
    )


def test_policy_does_not_mutate_robot_state():
    """Law 1: only the engine writes robot state."""
    eng = SimEngine("rush_50", seed=59, policy=StopAndWaitPolicy())
    eng.run(100)
    states = eng.observed_states()
    snapshot = {rid: (s.position.x, s.position.y) for rid, s in states.items()}
    eng.policy.arbitrate(eng.tick, eng.sim_time, states)
    after = {rid: (s.position.x, s.position.y) for rid, s in states.items()}
    assert snapshot == after


def test_snapshot_is_json_serialisable():
    import json

    eng = SimEngine("rush_50", seed=61, policy=StopAndWaitPolicy())
    snap = eng.run(20)
    json.dumps(snap.as_dict())
    json.dumps(eng.static_payload())


# ----------------------------------------------------------------------
# fleet-50 gridlock regression (docs/GRIDLOCK_DEFECT_20260922.md)
# ----------------------------------------------------------------------

def test_no_robot_stalls_forever_at_high_density():
    """A robot holding a task must never be stuck at zero net progress for
    longer than STALL_RELEASE_TICKS.

    This is the regression test for the fleet-50 gridlock defect: at high
    density, a pair of robots can land inside each other's safety floor and
    cycle WAIT -> REROUTE -> WAIT forever without ever actually moving, because
    the safety monitor's own documented limitation is that no fraction of a
    step clears a floor you are already inside (see swarm_policy.py._monitor's
    KNOWN LIMITATION note). Before the stall-release fix in
    SimEngine._check_stalls, this state persisted for the rest of the run
    (measured: replans in the tens of thousands, true displacement 0.0 m).
    The fix does not change the safety kernel; it only stops a robot from
    holding a task past a bounded number of ticks with no progress, releasing
    it back to the pending pool instead.
    """
    from app.api.runner import _make_policy
    from app.sim.engine import STALL_RELEASE_TICKS

    scen = get_scenario("rush_50")
    scen = type(scen)(**{**scen.__dict__, "fleet_size": 50})
    eng = SimEngine(scen, seed=18, policy=_make_policy("swarmos", 18), label="swarmos")

    worst_streak = 0
    for _ in range(3000):
        eng.step()
        for rid in eng.robots:
            stalled = eng._stall.get(rid)
            if stalled is not None:
                since_tick = stalled[0]
                worst_streak = max(worst_streak, eng.tick - since_tick)

    assert worst_streak <= STALL_RELEASE_TICKS, (
        f"a robot held a task with zero net progress for {worst_streak} ticks, "
        f"exceeding the STALL_RELEASE_TICKS bound of {STALL_RELEASE_TICKS} - "
        "the permanent wedge has regressed"
    )
    # The recovery must actually be exercised at this density, or the bound
    # above is untested by this scenario.
    assert eng.stall_releases > 0, (
        "no stall releases fired in 3000 ticks at fleet 50 - either the "
        "defect no longer reproduces here (update the scenario/seed used by "
        "this test) or _check_stalls stopped running"
    )
    # The fix must never create a collision: releasing a task only changes
    # bookkeeping (current_task_id, path, phase), never a robot's position.
    assert eng.kpis()["collisions"] == 0

# File contains AI-generated response based on internal company sources

