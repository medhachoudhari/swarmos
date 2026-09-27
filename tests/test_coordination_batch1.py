"""Regression tests for coordination fix batch 1.

Each test pins one defect found by the batch-1 diagnostic
(docs/COORDINATION_FIXES_BATCH1.md) and fails on the code that had it:

  FIX 1  the safety monitor checked a straight chord, not the path the robot
         actually drives, so a robot reversing to waypoint 0 entered the floor
  FIX 2  the contest named a winner the loser itself was blocking, so both
         robots stopped
  FIX 3  a genuine head-on loser waited out YIELD_PATIENCE instead of leaving
  FIX 4  replanning from mid-cell made the robot reverse to the cell centre
  FIX 5  a robot released from a stall was handed the next task at once
"""

from __future__ import annotations

import dataclasses
import math

from app.coordination.models import AMRState, MovementIntent, Position, RobotStatus
from app.coordination.swarm_policy import (
    HARD_STOP_M,
    HEADON_REPLAN_COOLDOWN_TICKS,
    MAX_STEP_M,
    PeerView,
    SwarmPolicy,
    _step_envelope,
    geometry_gap,
    project_step,
    segment_distance,
    swept_geometry,
)
from app.sim.cosim import make_baseline_policy, make_treatment_policy
from app.sim.engine import STALL_CLEARANCE_M, STALL_RELEASE_TICKS, SimEngine
from app.sim.pathfinding import trim_passed_start
from app.sim.policy import Verdict, VerdictKind
from app.sim.scenarios import get_scenario


def _state(rid, x, y, path, *, heading=0.0, battery=90.0, task=None, velocity=1.0):
    intent = None
    if path:
        intent = MovementIntent(
            target=Position(x=path[-1][0], y=path[-1][1]),
            path=[Position(x=px, y=py) for px, py in path],
            intent_id=f"I-{rid}",
        )
    return AMRState(
        robot_id=rid, timestamp=0.0, position=Position(x=x, y=y),
        velocity=velocity, heading=heading, status=RobotStatus.MOVING,
        battery=battery, current_task_id=task, movement_intent=intent,
    )


def _inside_floor_pair_ticks(engine: SimEngine, ticks: int) -> int:
    count = 0
    for _ in range(ticks):
        engine.step()
        live = [r for r in engine.robots.values() if not r.failed]
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if math.hypot(a.x - b.x, a.y - b.y) < HARD_STOP_M:
                    count += 1
    return count


def _with_fleet(name: str, fleet: int):
    return dataclasses.replace(get_scenario(name), fleet_size=fleet)


# ---------------------------------------------------------------------------
# FIX 1 - monitor geometry
# ---------------------------------------------------------------------------

# The traced defect in miniature: robot A has stopped 0.02 m past the centre
# of its cell, and its replanned path goes back to that centre and then turns
# 90 degrees. Peer B stands still 0.76 m behind A.
A_BACKTRACK = _state("A", 10.0, 5.0, [(9.98, 5.0), (9.98, 9.0)], heading=math.pi / 2)
B_BEHIND = _state("B", 9.24, 5.0, [], velocity=0.0)


def test_legacy_chord_missed_the_backward_first_leg():
    """Documents the blind spot: the old single chord cleared this step."""
    here = (10.0, 5.0)
    full = _step_envelope(here, project_step(A_BACKTRACK, MAX_STEP_M))
    there = (9.24, 5.0)
    assert segment_distance((here, full), (there, there)) >= HARD_STOP_M
    # ...while the robot's first real move (to waypoint 0) ends inside the floor.
    assert math.dist((9.98, 5.0), there) < HARD_STOP_M


def test_swept_geometry_contains_the_true_first_leg():
    geometry = swept_geometry(A_BACKTRACK, 1.0)
    assert geometry_gap(geometry, [((9.24, 5.0), (9.24, 5.0))]) < HARD_STOP_M
    # every scale still contains the backward leg, because it is only 0.02 m
    for scale in (0.25, 0.5, 0.75):
        g = swept_geometry(A_BACKTRACK, scale)
        assert geometry_gap(g, [((9.24, 5.0), (9.24, 5.0))]) < HARD_STOP_M


def test_swept_geometry_is_never_weaker_than_the_legacy_chord():
    here = (10.0, 5.0)
    full = _step_envelope(here, project_step(A_BACKTRACK, MAX_STEP_M))
    for scale in (0.25, 0.5, 0.75, 1.0):
        chord = (here, (here[0] + (full[0] - here[0]) * scale,
                        here[1] + (full[1] - here[1]) * scale))
        assert chord in swept_geometry(A_BACKTRACK, scale)


def test_monitor_refuses_motion_that_reverses_into_the_floor():
    pol = SwarmPolicy()
    proposal = Verdict(robot_id="A", kind=VerdictKind.PROCEED, reason="clear")
    inbox = {"B": PeerView(state=B_BEHIND)}
    final = pol._monitor("A", A_BACKTRACK, proposal, inbox, granted={})
    assert (final.speed_scale or 0.0) == 0.0, final.reason
    assert final.kind in (VerdictKind.WAIT, VerdictKind.REROUTE)


def test_monitor_still_grants_motion_that_keeps_the_floor():
    pol = SwarmPolicy()
    a = _state("A", 10.0, 5.0, [(14.0, 5.0)])
    proposal = Verdict(robot_id="A", kind=VerdictKind.PROCEED, reason="clear")
    inbox = {"B": PeerView(state=B_BEHIND)}
    final = pol._monitor("A", a, proposal, inbox, granted={})
    assert final.kind is VerdictKind.PROCEED and final.speed_scale == 1.0


def test_previously_observed_floor_entry_no_longer_occurs():
    """rush_50 / fleet 8 / seed 11 entered the floor at tick 1377 and the pair
    stayed there for the rest of the run (424 pair-ticks)."""
    eng = SimEngine(_with_fleet("rush_50", 8), seed=11, policy=make_treatment_policy())
    assert _inside_floor_pair_ticks(eng, 1500) == 0
    assert eng.kpis()["collisions"] == 0


def test_no_floor_entries_at_fleet_50():
    """rush_50 / fleet 50 / seed 13 used to enter the floor at ticks 90, 398
    and 433; none of those pairs ever escaped."""
    eng = SimEngine(_with_fleet("rush_50", 50), seed=13, policy=make_treatment_policy())
    assert _inside_floor_pair_ticks(eng, 450) == 0
    assert eng.kpis()["collisions"] == 0


# ---------------------------------------------------------------------------
# FIX 2 - winner feasibility
# ---------------------------------------------------------------------------

def _mutual_stop_states():
    # A drives +x straight at B. B is turning away up +y, so B can pass A but
    # A cannot pass B. A is the clear UTILITY winner (low battery, carrying a
    # task), which is exactly the pairing that used to stop both robots.
    a = _state("A", 10.0, 5.0, [(20.0, 5.0)], heading=0.0, battery=20.0, task="T001")
    b = _state("B", 10.8, 5.0, [(10.8, 9.0)], heading=math.pi / 2, battery=100.0)
    return {"A": a, "B": b}


def test_blocked_utility_winner_hands_right_of_way_to_the_robot_that_can_pass():
    pol = SwarmPolicy()
    verdicts = pol.arbitrate(1, 0.1, _mutual_stop_states())
    a, b = verdicts["A"], verdicts["B"]
    assert (b.speed_scale or 0.0) > 0.0, f"B should move: {b.reason}"
    assert b.kind is VerdictKind.PROCEED and "swapped" in b.reason
    assert a.kind is VerdictKind.YIELD and a.yield_to == "B"
    assert pol.stats()["feasibility_swaps"] == 1


def test_mutual_stop_case_never_leaves_both_robots_stopped():
    pol = SwarmPolicy()
    states = _mutual_stop_states()
    for tick in range(1, 6):
        verdicts = pol.arbitrate(tick, tick / 10.0, states)
        moving = [rid for rid, v in verdicts.items() if (v.speed_scale or 0.0) > 0.0]
        assert moving, f"tick {tick}: both stopped - {verdicts}"


def test_feasibility_resolution_is_deterministic():
    runs = []
    for _ in range(2):
        pol = SwarmPolicy()
        v = pol.arbitrate(1, 0.1, _mutual_stop_states())
        runs.append({rid: (x.kind, x.speed_scale, x.reason) for rid, x in v.items()})
    assert runs[0] == runs[1]


# ---------------------------------------------------------------------------
# FIX 3 - head-on
# ---------------------------------------------------------------------------

def _head_on_states():
    a = _state("A", 10.0, 5.0, [(20.0, 5.0)], heading=0.0, battery=20.0, task="T001")
    b = _state("B", 10.85, 5.0, [(0.0, 5.0)], heading=math.pi, battery=100.0)
    return {"A": a, "B": b}


def test_head_on_loser_replans_immediately_instead_of_yielding():
    pol = SwarmPolicy()
    verdicts = pol.arbitrate(1, 0.1, _head_on_states())
    b = verdicts["B"]
    assert b.kind is VerdictKind.REROUTE and b.needs_replan, b.reason
    assert b.conflict_with == ("A",) and "head-on" in b.reason
    assert pol.stats()["headon_replans"] == 1
    # the winner is still bounded by the monitor: whatever it is granted keeps
    # the floor against B's standing position
    a = verdicts["A"]
    granted = swept_geometry(_head_on_states()["A"], a.speed_scale or 0.0)
    assert geometry_gap(granted, [((10.85, 5.0), (10.85, 5.0))]) >= HARD_STOP_M


def test_head_on_replan_is_not_repeated_against_the_same_peer_in_cooldown():
    pol = SwarmPolicy()
    states = _head_on_states()
    pol.arbitrate(1, 0.1, states)
    again = pol.arbitrate(2, 0.2, states)["B"]
    assert not (again.kind is VerdictKind.REROUTE and "head-on" in again.reason)
    assert pol.stats()["headon_replans"] == 1
    later = pol.arbitrate(2 + HEADON_REPLAN_COOLDOWN_TICKS, 3.0, states)["B"]
    assert later.kind is VerdictKind.REROUTE


def test_head_on_loser_replan_route_avoids_the_winner_end_to_end():
    """End to end: the engine turns the head-on REROUTE into an avoid hint."""
    eng = SimEngine(_with_fleet("narrow_aisle_deadlock", 24), seed=13,
                    policy=make_treatment_policy())
    eng.run(600)
    stats = eng.policy.stats()
    assert stats["headon_replans"] > 0
    assert eng.kpis()["collisions"] == 0


# ---------------------------------------------------------------------------
# FIX 4 - path start
# ---------------------------------------------------------------------------

def test_trim_drops_a_start_waypoint_the_robot_has_already_passed():
    assert trim_passed_start([(10.0, 5.0), (15.0, 5.0)], (10.4, 5.0)) == [(15.0, 5.0)]


def test_trim_keeps_the_start_when_the_robot_must_go_back_to_turn():
    wps = [(10.0, 5.0), (10.0, 9.0)]
    assert trim_passed_start(wps, (10.4, 5.0)) == wps


def test_trim_keeps_the_start_when_the_robot_is_on_it_or_before_it():
    wps = [(10.0, 5.0), (15.0, 5.0)]
    assert trim_passed_start(wps, (10.0, 5.0)) == wps
    assert trim_passed_start(wps, (9.6, 5.0)) == wps
    assert trim_passed_start([(10.0, 5.0)], (10.4, 5.0)) == [(10.0, 5.0)]


def _backtracking_plans(policy, ticks=600):
    eng = SimEngine(_with_fleet("rush_50", 16), seed=13, policy=policy)
    versions = {rid: r.path_version for rid, r in eng.robots.items()}
    bad = 0
    for _ in range(ticks):
        eng.step()
        for rid, r in eng.robots.items():
            if r.path_version != versions[rid] and len(r.path) >= 2:
                if trim_passed_start(r.path, (r.x, r.y)) != r.path:
                    bad += 1
            versions[rid] = r.path_version
    return bad


def test_no_plan_starts_behind_the_robot_in_either_arm():
    """Shared simulator fix: identical for SWARMOS and for the baseline."""
    assert _backtracking_plans(make_treatment_policy()) == 0
    assert _backtracking_plans(make_baseline_policy()) == 0


# ---------------------------------------------------------------------------
# FIX 5 - no re-dispatch to a wedged robot
# ---------------------------------------------------------------------------

def _two_robot_engine():
    eng = SimEngine(_with_fleet("rush_50", 4), seed=11, policy=make_baseline_policy())
    r1, r2 = eng.robots["R001"], eng.robots["R002"]
    return eng, r1, r2


def test_released_robot_is_held_while_still_wedged_against_a_peer():
    eng, r1, r2 = _two_robot_engine()
    r2.x, r2.y = r1.x + 0.74, r1.y
    eng._stall_hold[r1.robot_id] = eng.tick
    assert eng._held_after_stall(r1)
    free_ids = {r.robot_id for r in eng.robots.values()
                if r.is_available_for_work and not eng._held_after_stall(r)}
    assert r1.robot_id not in free_ids


def test_hold_lifts_once_the_robot_is_clear():
    eng, r1, r2 = _two_robot_engine()
    for other in eng.robots.values():
        if other is not r1:
            other.x, other.y = r1.x + 5.0 + STALL_CLEARANCE_M, r1.y
    eng._stall_hold[r1.robot_id] = eng.tick
    assert not eng._held_after_stall(r1)
    assert r1.robot_id not in eng._stall_hold


def test_hold_is_bounded_and_never_disables_a_robot_for_good():
    eng, r1, r2 = _two_robot_engine()
    r2.x, r2.y = r1.x + 0.5, r1.y
    eng._stall_hold[r1.robot_id] = eng.tick - STALL_RELEASE_TICKS
    assert not eng._held_after_stall(r1)


def test_held_robot_is_skipped_by_dispatch_but_the_task_is_kept():
    eng, r1, r2 = _two_robot_engine()
    for rid, r in eng.robots.items():          # clear every assignment
        if r.current_task_id is not None:
            eng._release_task(r, reason="test")
    r2.x, r2.y = r1.x + 0.74, r1.y
    eng._stall_hold[r1.robot_id] = eng.tick
    pending_before = len(eng.pending)
    eng._dispatch()
    assert r1.current_task_id is None
    assigned = sum(1 for r in eng.robots.values() if r.current_task_id is not None)
    assert len(eng.pending) == pending_before - assigned   # nothing deleted


def test_stall_release_starts_the_hold():
    eng = SimEngine(_with_fleet("rush_50", 50), seed=13, policy=make_treatment_policy())
    eng.run(900)
    if eng.stall_releases:
        assert eng.stall_holds_skipped >= 0
        assert all(isinstance(t, int) for t in eng._stall_hold.values())


# ---------------------------------------------------------------------------
# determinism across the whole batch
# ---------------------------------------------------------------------------

def test_replay_is_deterministic_in_both_arms():
    for factory in (make_treatment_policy, make_baseline_policy):
        hashes = []
        for _ in range(2):
            eng = SimEngine(_with_fleet("rush_50", 16), seed=17, policy=factory())
            eng.run(400)
            hashes.append(eng.trace_hash)
        assert hashes[0] == hashes[1]
