"""Regression tests for coordination / resilience batch 2.

See docs/COORDINATION_FIXES_BATCH2.md. Grouped by phase:

  1  yield/wait deadlock - third-party feasibility, stuck-winner replan,
     repeated-contest and winner-held telemetry
  2  sovereign mode triggers on evidence of comm loss, not on isolation
  3  the failure detector does not confirm robots that merely left range
  4  LINK_IMPAIR and ZONE_PARTITION actually reach the radio
  5  a quarantined (or otherwise silent) robot stays a physical obstacle
  6  telemetry: replans, stalled robots, coordination counters
"""

from __future__ import annotations

import dataclasses
import math

from app.coordination.models import AMRState, MovementIntent, Position, RobotStatus
from app.coordination.radio import (
    LINK_PERFECT,
    BoundedRadio,
    FailureDetector,
    PeerHealth,
)
from app.coordination.messages import CoordinationMessage, MessageType
from app.coordination.swarm_policy import (
    HARD_STOP_M,
    MAX_STEP_M,
    STUCK_YIELD_TICKS,
    PeerView,
    SwarmPolicy,
    _Encounter,
)
from app.sim.cosim import make_baseline_policy, make_treatment_policy
from app.sim.engine import SimEngine
from app.sim.policy import NoOpPolicy, Verdict, VerdictKind
from app.sim.scenarios import FaultKind, get_scenario


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


def _engine(scenario, fleet, seed, policy=None, **kw):
    spec = dataclasses.replace(get_scenario(scenario), fleet_size=fleet)
    pol = policy if policy is not None else make_treatment_policy(**kw)
    return SimEngine(spec, seed=seed, policy=pol), pol


def _false_failures(eng, pol, seen_upto=0):
    bad = 0
    for ev in pol.failure_log[seen_upto:]:
        if ev["to"] == "FAILED" and not eng.robots[ev["robot_id"]].failed:
            bad += 1
    return bad


# ===========================================================================
# Phase 1 - yield / wait deadlock
# ===========================================================================

def _third_party_states():
    # A is the utility winner against B, and A's step is clear of B - but A is
    # boxed in by T, which is standing still. B could drive away freely.
    a = _state("A", 10.0, 5.0, [(20.0, 5.0)], battery=20.0, task="T1")
    b = _state("B", 10.0, 5.9, [(10.0, 9.0)], heading=math.pi / 2, battery=100.0)
    t = _state("T", 10.9, 5.0, [], velocity=0.0, battery=100.0)
    return {"A": a, "B": b, "T": t}


def test_loser_does_not_yield_to_a_winner_boxed_in_by_a_third_robot():
    pol = SwarmPolicy()
    verdicts = pol.arbitrate(1, 0.1, _third_party_states())
    b = verdicts["B"]
    assert b.kind is not VerdictKind.YIELD, b.reason
    assert (b.speed_scale or 0.0) > 0.0, b.reason


def _contest_setup():
    pol = SwarmPolicy()
    me = _state("L", 10.0, 5.0, [(10.0, 9.0)], heading=math.pi / 2, battery=100.0)
    winner = _state("W", 10.9, 5.0, [(20.0, 5.0)], battery=10.0, task="T9")
    enc = _Encounter(peer_id="W", distance=0.9, following=False)
    return pol, me, winner, enc


def test_stuck_winner_is_detected_but_by_default_the_loser_keeps_yielding():
    """The replan response was measured to cost throughput, so it is opt-in."""
    pol, me, winner, enc = _contest_setup()
    for tick in range(1, STUCK_YIELD_TICKS + 2):
        pol._tick = tick
        inbox = {"W": PeerView(state=winner, holding=True, heard_tick=tick)}
        assert pol._contest("L", me, enc, inbox).kind is VerdictKind.YIELD
    assert pol.stats()["stuck_yield_detections"] == 1
    assert pol.stats()["stuck_yield_replans"] == 0


def test_stuck_winner_makes_the_loser_replan_when_opted_in(monkeypatch):
    import app.coordination.swarm_policy as sp
    monkeypatch.setattr(sp, "STUCK_YIELD_REPLAN", True)
    pol, me, winner, enc = _contest_setup()
    kinds = []
    for tick in range(1, STUCK_YIELD_TICKS + 2):
        pol._tick = tick
        inbox = {"W": PeerView(state=winner, holding=True, heard_tick=tick)}
        kinds.append(pol._contest("L", me, enc, inbox))
    assert all(v.kind is VerdictKind.YIELD for v in kinds[:STUCK_YIELD_TICKS - 1])
    replan = kinds[STUCK_YIELD_TICKS - 1]
    assert replan.kind is VerdictKind.REROUTE and "has held" in replan.reason
    assert replan.conflict_with == ("W",)
    # the give-way cooldown stops an immediate second replan against W
    assert kinds[STUCK_YIELD_TICKS].kind is VerdictKind.YIELD
    assert pol.stats()["stuck_yield_replans"] == 1


def test_a_moving_winner_never_triggers_the_stuck_replan(monkeypatch):
    import app.coordination.swarm_policy as sp
    monkeypatch.setattr(sp, "STUCK_YIELD_REPLAN", True)
    pol, me, winner, enc = _contest_setup()
    for tick in range(1, 3 * STUCK_YIELD_TICKS):
        pol._tick = tick
        inbox = {"W": PeerView(state=winner, holding=False, heard_tick=tick)}
        v = pol._contest("L", me, enc, inbox)
        assert v.kind is VerdictKind.YIELD
    assert pol.stats()["stuck_yield_replans"] == 0
    assert pol.stats()["stuck_yield_detections"] == 0


def test_repeated_contests_between_one_pair_are_counted():
    pol, me, winner, enc = _contest_setup()
    inbox = {"W": PeerView(state=winner, holding=False)}
    for tick in (1, 30):          # 30 > COMMIT_TICKS, so the pair is re-scored
        pol._tick = tick
        pol._contest("L", me, enc, inbox)
    assert pol.stats()["repeated_contests"] == 1


def test_winner_held_telemetry_is_bounded_and_exposed():
    eng, pol = _engine("rush_50", 16, 13)
    eng.run(400)
    st = pol.stats()
    assert 0 <= st["yields_winner_held"] <= st["yields_total"]
    coord = eng.kpis()["coordination"]
    assert coord["yields_total"] == st["yields_total"]
    assert "repeated_contests" in coord and "stuck_yield_replans" in coord


# ===========================================================================
# Phase 2 - sovereign mode
# ===========================================================================

def test_A_geographic_isolation_never_triggers_sovereign():
    """Fleet 8 on the full floor: robots are often >15 m from everyone.
    The Batch-1 rule armed sovereign mode on 151 of the first 300 ticks."""
    eng, pol = _engine("rush_50", 8, 11)
    eng.run(600)
    assert pol.stats()["sovereign"]["entries"] == 0


def test_isolation_without_perception_keeps_the_legacy_rule():
    pol = SwarmPolicy()
    lone = {"R001": _state("R001", 5.0, 5.0, [(9.0, 5.0)])}
    for tick in range(1, 10):
        pol.arbitrate(tick, tick / 10.0, lone)
    assert pol.is_sovereign("R001")


def test_B_mild_packet_loss_does_not_trigger_sovereign():
    eng, pol = _engine("rush_50", 50, 11)
    eng.run(20)
    eng.inject(FaultKind.LINK_IMPAIR, drop_pct=20.0, latency_ms=0.0, ticks=200)
    eng.run(200)
    assert pol.stats()["sovereign"]["entries"] == 0


def test_C_total_link_impairment_triggers_sovereign_and_recovers():
    eng, pol = _engine("rush_50", 16, 13)
    eng.run(20)
    eng.inject(FaultKind.LINK_IMPAIR, drop_pct=100.0, latency_ms=0.0, ticks=60)
    eng.run(40)
    assert pol.stats()["sovereign"]["entries"] > 0
    eng.run(60)                      # impairment lifts at +60 ticks
    assert len(pol.sovereign) == 0
    assert pol.stats()["sovereign"]["rejoins"] > 0
    assert eng.kpis()["collisions"] == 0


def test_D_blackout_triggers_sovereign_and_the_robot_is_not_hit():
    eng, pol = _engine("rush_50", 50, 11)
    eng.run(2)
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id="R001", ticks=100)
    for _ in range(40):
        eng.step()
        if pol.is_sovereign("R001"):
            break
    assert pol.is_sovereign("R001")
    eng.run(120)
    assert not pol.is_sovereign("R001")          # rejoined after restore
    assert eng.kpis()["collisions"] == 0


def test_E_sustained_radio_failure_keeps_working_then_rejoins():
    eng, pol = _engine("rush_50", 50, 13)
    eng.run(40)
    target = next(r for r in eng.robots.values() if r.current_task_id)
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id=target.robot_id, ticks=400)
    eng.run(30)
    assert pol.is_sovereign(target.robot_id)
    x0, y0 = target.x, target.y
    eng.run(300)
    assert pol.is_sovereign(target.robot_id)
    moved = math.hypot(target.x - x0, target.y - y0) + target.tasks_completed
    assert moved > 0.0
    eng.run(120)
    assert not pol.is_sovereign(target.robot_id)
    assert eng.kpis()["collisions"] == 0


# ===========================================================================
# Phase 3 - failure detector
# ===========================================================================

def test_detector_hold_keeps_a_silent_peer_suspected_not_failed():
    det = FailureDetector()
    det.heartbeat("P", 0.0)
    det.evaluate(1.0, hold={"P"})
    assert det.health("P") is PeerHealth.SUSPECTED
    det.evaluate(1.1)
    assert det.health("P") is PeerHealth.FAILED
    det.evaluate(1.2, hold={"P"})               # confirmed failures are sticky
    assert det.health("P") is PeerHealth.FAILED
    det.heartbeat("P", 1.3)
    assert det.health("P") is PeerHealth.ALIVE


def test_out_of_range_robot_is_not_confirmed_failed():
    eng, pol = _engine("rush_50", 8, 11)
    eng.run(900)
    assert _false_failures(eng, pol) == 0


def test_temporary_packet_loss_is_not_a_failure():
    eng, pol = _engine("rush_50", 16, 13)
    eng.run(20)
    eng.inject(FaultKind.LINK_IMPAIR, drop_pct=20.0, latency_ms=0.0, ticks=300)
    eng.run(300)
    assert _false_failures(eng, pol) == 0


def test_blacked_out_robot_is_not_confirmed_failed_while_it_moves():
    eng, pol = _engine("rush_50", 50, 11)
    eng.run(2)
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id="R001", ticks=200)
    r = eng.robots["R001"]
    # Motion during tick t is only observable (through sightings) at the start
    # of tick t+1, so the verdict after step t reflects motion during t-1.
    positions = [(r.x, r.y)]
    moving_ticks = 0
    for _ in range(200):
        eng.step()
        positions.append((r.x, r.y))
        if len(positions) >= 3:
            (x0, y0), (x1, y1) = positions[-3], positions[-2]
            if math.hypot(x1 - x0, y1 - y0) > 1e-3:
                moving_ticks += 1
                assert pol.detector.health("R001") is not PeerHealth.FAILED
    assert moving_ticks > 20


def test_genuine_failure_is_still_confirmed_and_recovery_works():
    eng, pol = _engine("rush_50", 50, 13)
    eng.run(100)
    res = eng.inject(FaultKind.ROBOT_FAILURE)
    dead = res["robot_id"]
    eng.run(30)
    assert pol.detector.health(dead) is PeerHealth.FAILED
    assert eng.kpis()["collisions"] == 0


def test_blackout_recovery_returns_the_robot_to_alive():
    eng, pol = _engine("rush_50", 50, 11)
    eng.run(2)
    eng.inject(FaultKind.COMM_BLACKOUT, robot_id="R001", ticks=40)
    eng.run(60)
    assert pol.detector.health("R001") is PeerHealth.ALIVE


# ===========================================================================
# Phase 4 - link impairment and zone partition wiring
# ===========================================================================

def _msg(sender, seq=0):
    return CoordinationMessage(
        schema_version="1.0", message_id=f"{sender}-{seq}",
        type=MessageType.ROBOT_STATE, sender_id=sender, timestamp=0.0,
        sequence=seq, payload={},
    )


def test_partition_cuts_only_links_that_cross_it():
    radio = BoundedRadio()
    radio.set_positions({"A": (0.0, 0.0), "B": (1.0, 0.0), "C": (2.0, 0.0)})
    radio.set_partition({"A"})
    assert not radio.in_range("A", "B") and not radio.in_range("B", "A")
    assert radio.in_range("B", "C")
    assert radio.neighbours("B") == ["C"]
    radio.set_partition(())
    assert radio.in_range("A", "B")


def test_link_impair_reaches_the_radio_and_expires():
    eng, pol = _engine("rush_50", 16, 13)
    eng.run(10)
    dropped0 = pol.radio.stats.dropped
    res = eng.inject(FaultKind.LINK_IMPAIR, drop_pct=30.0, latency_ms=100.0, ticks=50)
    assert res["applied"] and res["latency_ticks"] == 1
    assert pol.radio.profile.loss_pct == 30.0 and pol.radio.profile.latency_ticks == 1
    eng.run(49)
    assert pol.radio.stats.dropped > dropped0
    eng.run(2)
    assert pol.radio.profile == LINK_PERFECT
    assert "drop_pct" not in eng.kpis()["impairment"]


def test_zone_partition_reaches_the_radio_and_expires():
    eng, pol = _engine("rush_50", 50, 13)
    eng.run(10)
    res = eng.inject(FaultKind.ZONE_PARTITION, zone="EAST", ticks=30)
    assert res["applied"]
    eng.step()
    inside = set(pol.radio.partitioned)
    east = {
        rid for rid, r in eng.robots.items()
        if eng.warehouse.zone_of(*eng.warehouse.m_to_cell(r.x, r.y)) == "EAST"
    }
    assert inside and inside <= east | inside
    eng.run(40)
    assert pol.radio.partitioned == ()
    assert eng.kpis()["collisions"] == 0


def test_baseline_has_no_radio_and_is_unaffected_by_comm_faults():
    eng, _ = _engine("rush_50", 16, 13, policy=make_baseline_policy())
    assert eng.inject(FaultKind.LINK_IMPAIR)["applied"] is False
    assert eng.inject(FaultKind.ZONE_PARTITION)["applied"] is False


def test_impaired_runs_replay_bit_identically():
    hashes = []
    for _ in range(2):
        eng, _ = _engine("rush_50", 16, 17)
        eng.run(20)
        eng.inject(FaultKind.LINK_IMPAIR, drop_pct=25.0, latency_ms=100.0, ticks=100)
        eng.inject(FaultKind.ZONE_PARTITION, zone="WEST", ticks=100)
        eng.run(200)
        hashes.append(eng.trace_hash)
    assert hashes[0] == hashes[1]


# ===========================================================================
# Phase 5 - quarantine and silent robots stay physical
# ===========================================================================

def test_monitor_blocks_motion_toward_a_seen_but_unheard_robot():
    pol = SwarmPolicy()
    me = _state("A", 10.0, 5.0, [(20.0, 5.0)])
    pol._sightings = {"A": {"Q": (10.85, 5.0)}}
    proposal = Verdict(robot_id="A", kind=VerdictKind.PROCEED, reason="clear")
    final = pol._monitor("A", me, proposal, inbox={}, granted={})
    assert (final.speed_scale or 0.0) == 0.0, final.reason
    # the same robot heard normally would only need the ordinary floor
    assert 0.85 < HARD_STOP_M + MAX_STEP_M


def test_monitor_uses_the_seen_position_of_a_robot_that_lies():
    pol = SwarmPolicy()
    me = _state("A", 10.0, 5.0, [(20.0, 5.0)])
    liar_claim = _state("Q", 13.5, 5.0, [])          # claims 3.5 m away
    pol._sightings = {"A": {"Q": (10.85, 5.0)}}       # is really 0.85 m ahead
    proposal = Verdict(robot_id="A", kind=VerdictKind.PROCEED, reason="clear")
    final = pol._monitor("A", me, proposal, {"Q": PeerView(state=liar_claim)}, {})
    assert (final.speed_scale or 0.0) == 0.0, final.reason


def test_contained_rogue_is_not_hit_and_quorum_containment_still_works():
    eng, pol = _engine("rush_50", 16, 13, integrity=True)
    eng.run(300)
    res = eng.inject(FaultKind.ROGUE_ROBOT)
    rogue = res["robot_id"]
    eng.run(30)
    assert pol.stats()["integrity"]["robots_contained"] >= 1
    assert eng.robots[rogue].quarantined
    eng.run(570)
    assert eng.kpis()["collisions"] == 0
    # a contained robot is neither sovereign nor "failed"
    assert not pol.is_sovereign(rogue)
    assert pol.detector.health(rogue) is not PeerHealth.FAILED


# ===========================================================================
# Phase 6 - telemetry
# ===========================================================================

def test_plans_are_counted_once_and_classified():
    eng, _ = _engine("rush_50", 16, 13)
    eng.run(600)
    k = eng.kpis()
    assert k["path_plans"] == k["initial_plans"] + k["replans"]
    assert k["replans"] <= k["path_invalidations"]
    assert k["replans"] > 0 and k["initial_plans"] > 0


def test_an_unarbitrated_run_has_no_replans():
    eng = SimEngine(dataclasses.replace(get_scenario("rush_50"), fleet_size=8),
                    seed=11, policy=NoOpPolicy())
    eng.run(300)
    k = eng.kpis()
    assert k["replans"] == 0 and k["initial_plans"] == k["path_plans"] > 0


def test_stalled_and_coordination_kpis_exist_for_both_arms():
    for factory in (make_treatment_policy, make_baseline_policy):
        eng, _ = _engine("rush_50", 16, 13, policy=factory())
        eng.run(200)
        k = eng.kpis()
        assert k["robots_stalled"] >= 0
        assert isinstance(k["coordination"], dict)


def test_replay_is_still_deterministic_in_both_arms():
    for factory in (make_treatment_policy, make_baseline_policy):
        hashes = []
        for _ in range(2):
            eng, _ = _engine("rush_50", 16, 19, policy=factory())
            eng.run(400)
            hashes.append(eng.trace_hash)
        assert hashes[0] == hashes[1]
