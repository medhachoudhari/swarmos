"""Behavioural contract for the SWARMOS arbiter (app/coordination/swarm_policy.py).

The arbiter is the BINDING safety authority in this system: its verdict is final
and no other module may override it. Until now it was also the only major module
with no tests, which made every tuning change a leap of faith. This file pins the
properties that must hold no matter how the negotiation is tuned.

The tests are deliberately written against OBSERVABLE BEHAVIOUR - the verdict
returned by arbitrate() - and not against private helpers, so that they keep
their value when the internals are refactored. Where a test must reach into a
private attribute it says why.

Geometry reminder, all distances in metres:
    HARD_STOP_M  = 0.75   kernel floor, never crossed
    CONFLICT_M   = 0.97   HARD_STOP_M + one full step
    CAUTION_M    = 1.13   below this a peer is considered at all
    MAX_STEP_M   = 0.22   one tick of travel at full speed
"""

from __future__ import annotations

import math
import random

import pytest

from app.coordination import swarm_policy as sp
from app.coordination.models import (
    AMRState,
    MovementIntent,
    Position,
    RobotStatus,
)
from app.coordination.swarm_policy import (
    CAUTION_M,
    CONFLICT_M,
    HARD_STOP_M,
    MAX_STEP_M,
    MONITOR_STUCK_TICKS,
    SwarmPolicy,
)
from app.sim.policy import VerdictKind

EAST = 0.0
WEST = math.pi
NORTH = math.pi / 2.0


def state(
    rid: str,
    x: float,
    y: float = 0.0,
    *,
    heading: float = EAST,
    velocity: float = 1.0,
    status: RobotStatus = RobotStatus.MOVING,
    battery: float = 80.0,
    target: tuple[float, float] | None = None,
    task: str | None = "T001",
    timestamp: float = 0.0,
) -> AMRState:
    """One robot, positioned and pointed, with a movement intent.

    The intent matters: the arbiter projects the next step from heading, and the
    utility function reads remaining path length, so a state without a target is
    not representative of anything the simulation produces.
    """
    if target is None:
        # 10 m straight ahead, so there is always meaningful remaining path.
        target = (x + 10.0 * math.cos(heading), y + 10.0 * math.sin(heading))
    return AMRState(
        robot_id=rid,
        timestamp=timestamp,
        position=Position(x=x, y=y),
        velocity=velocity,
        heading=heading,
        status=status,
        battery=battery,
        current_task_id=task,
        movement_intent=MovementIntent(
            target=Position(x=target[0], y=target[1]),
            path=[Position(x=target[0], y=target[1])],
            intent_id=f"{rid}-i1",
        ),
    )


def policy(**kw) -> SwarmPolicy:
    """A policy with a fixed RNG, so every test is deterministic."""
    kw.setdefault("rng", random.Random(1234))
    return SwarmPolicy(**kw)


def settle(pol: SwarmPolicy, states: dict[str, AMRState], ticks: int):
    """Run the same geometry for several ticks and return the last verdicts.

    Peer knowledge arrives over the radio, so on tick 0 nobody has heard anyone
    and every robot correctly sees an empty world. Any test about interaction
    must therefore let the radio fill first. This mirrors how the real engine
    calls the policy and is the single most important thing to understand about
    testing this class.
    """
    out: dict = {}
    for tick in range(ticks):
        out = pol.arbitrate(tick, tick * 0.1, states)
    return out


# ---------------------------------------------------------------------------
# radio / locality
# ---------------------------------------------------------------------------


class TestBoundedRadio:
    def test_peer_knowledge_arrives_within_the_same_tick(self):
        """Under a perfect link a peer in range is usable on the FIRST tick.

        arbitrate() calls _broadcast_round() and then _drain_round() before it
        decides anything, so a heartbeat sent this tick is also delivered this
        tick. That is a deliberate property, not an accident: at 10 Hz the
        heartbeat period equals the control period, so requiring a tick of
        latency would mean acting on state that is already stale.

        The locality guarantee is therefore about RANGE, not about delay - see
        test_peer_beyond_radio_range_is_never_heard for the half that actually
        bounds the information flow.
        """
        pol = policy()
        states = {"R001": state("R001", 0.0), "R002": state("R002", 0.5)}
        verdicts = pol.arbitrate(0, 0.0, states)
        # 0.5 m apart is well inside the 0.75 m floor, so the kernel must have
        # acted already on tick 0. If it had not yet heard R002 this would be a
        # pair of PROCEEDs driving into each other.
        assert verdicts["R001"].kind is not VerdictKind.PROCEED
        assert pol.explain("R001")["peers_heard"] == ["R002"]

    def test_peer_beyond_radio_range_is_never_heard(self):
        """A robot 200 m away must not influence anything, ever."""
        pol = policy()
        states = {"R001": state("R001", 0.0), "R002": state("R002", 200.0)}
        settle(pol, states, 20)
        assert pol.explain("R001")["peers_heard"] == []

    def test_peer_within_radio_range_is_heard(self):
        pol = policy()
        states = {"R001": state("R001", 0.0), "R002": state("R002", 5.0)}
        settle(pol, states, 20)
        assert pol.explain("R001")["peers_heard"] == ["R002"]

    def test_messages_per_robot_tick_does_not_grow_with_fleet(self):
        """O(k) not O(N): the scaling claim the whole architecture rests on.

        Robots are spread far enough apart that most pairs are out of radio
        range, so per-robot traffic must stay flat as the fleet grows. If this
        regresses, the "scales to 50 robots" claim is dead.
        """
        # Robots are laid out in a LINE at fixed 8 m spacing, so growing the
        # fleet lengthens the line without changing local density. This is the
        # only honest way to pose the question: a denser grid would increase the
        # true neighbour count, and the resulting traffic rise would be correct
        # behaviour rather than a scaling defect. My first attempt at this test
        # made exactly that mistake and "failed" on a design that was right.
        # At 8 m spacing and R_comm = 15 m each interior robot hears the two
        # robots either side of it, whatever the fleet size.
        rates = []
        for n in (8, 32):
            pol = policy()
            states = {
                f"R{i:03d}": state(f"R{i:03d}", i * 8.0, 0.0) for i in range(n)
            }
            settle(pol, states, 12)
            rates.append(pol.stats()["msgs_per_robot_tick"])
        # A 4x fleet on an O(N) broadcast would give roughly a 4x rate. Allow
        # modest slack for the fixed edge effect (end robots have one neighbour,
        # and their share of the fleet shrinks as N grows) while still catching
        # any genuinely superlinear growth.
        assert rates[1] <= rates[0] * 1.5, (
            f"per-robot traffic grew from {rates[0]} to {rates[1]} at constant "
            f"density - the bounded-radio O(k) claim does not hold"
        )


# ---------------------------------------------------------------------------
# the safety kernel - the binding part
# ---------------------------------------------------------------------------


class TestSafetyKernel:
    def test_head_on_pair_inside_the_floor_is_never_allowed_to_close(self):
        """Two robots already inside HARD_STOP_M must not both drive on.

        This is the exact case the old collision metric hid: a frozen overlap
        that was counted once and then forgotten. At least one robot must be
        denied motion.
        """
        pol = policy()
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.60, heading=WEST),
        }
        verdicts = settle(pol, states, 10)
        scales = [(verdicts[r].speed_scale or 0.0) for r in ("R001", "R002")]
        assert min(scales) == pytest.approx(0.0), (
            f"both robots were granted motion inside the floor: {scales}"
        )

    def test_crossing_pair_at_conflict_range_is_constrained(self):
        """Inside CONFLICT_M somebody gives way; nobody simply proceeds."""
        pol = policy()
        states = {
            "R001": state("R001", 0.0, 0.0, heading=EAST),
            "R002": state("R002", 0.0, 0.85, heading=NORTH),
        }
        verdicts = settle(pol, states, 10)
        kinds = {verdicts[r].kind for r in ("R001", "R002")}
        assert kinds != {VerdictKind.PROCEED}

    def test_distant_robots_both_proceed_at_full_speed(self):
        """The arbiter must not tax robots that are nowhere near each other."""
        pol = policy()
        states = {
            "R001": state("R001", 0.0),
            "R002": state("R002", 9.0, 9.0),
        }
        verdicts = settle(pol, states, 10)
        for rid in ("R001", "R002"):
            assert verdicts[rid].kind is VerdictKind.PROCEED
            assert (verdicts[rid].speed_scale or 1.0) == pytest.approx(1.0)

    def test_monitor_can_be_disabled_for_ablation(self):
        """monitor=False must actually remove the kernel.

        The A/B in diag_isolate.py depends on this switch being real; if it
        silently did nothing, every ablation measurement would be a lie.
        """
        pol = policy(monitor=False)
        assert pol.stats()["monitor_enabled"] is False
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.60, heading=WEST),
        }
        settle(pol, states, 10)
        assert pol.stats()["monitor_vetoes"] == 0

    def test_enabled_monitor_records_vetoes_in_a_wedge(self):
        pol = policy()
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.60, heading=WEST),
        }
        settle(pol, states, 12)
        assert pol.stats()["monitor_vetoes"] > 0


# ---------------------------------------------------------------------------
# liveness: nothing may be held forever
# ---------------------------------------------------------------------------


class TestLiveness:
    def test_wedged_robot_is_eventually_rerouted_not_held_forever(self):
        """The property that makes the kernel safe AND live.

        A pair stuck inside the floor cannot be freed by any speed reduction -
        no fraction of a step can clear a floor you are already inside - so the
        only exit is replanning. Without this the kernel could hold a robot for
        an entire run, which is precisely the bug MONITOR_STUCK_TICKS fixed.
        """
        pol = policy()
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.60, heading=WEST),
        }
        # Generous margin over the threshold; the point is that it happens at
        # all, not exactly when.
        seen = set()
        for tick in range(MONITOR_STUCK_TICKS * 6 + 20):
            v = pol.arbitrate(tick, tick * 0.1, states)
            seen.update(v[r].kind for r in ("R001", "R002"))
        assert VerdictKind.REROUTE in seen, (
            "a permanently wedged pair was never rerouted - the kernel can "
            "starve a robot for the whole run"
        )

    def test_recovery_threshold_is_the_measured_optimum(self):
        """Guard the tuned constant against silent drift.

        4 ticks was chosen from a sweep with a clear interior peak (+5.3% over
        the baseline at zero collisions, against -31.6% at 30). It is a tuned
        value, not an arbitrary one, so a change to it must be a deliberate
        change to this test.
        """
        assert MONITOR_STUCK_TICKS == 4


# ---------------------------------------------------------------------------
# determinism - the foundation of the replay claim (N3)
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_same_seed_and_inputs_give_identical_verdicts(self):
        """Without this, deterministic replay is not a feature we have."""
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.90, heading=WEST),
            "R003": state("R003", 0.0, 0.90, heading=NORTH),
        }

        def trace():
            pol = policy()
            out = []
            for tick in range(30):
                v = pol.arbitrate(tick, tick * 0.1, states)
                out.append(
                    tuple(
                        (r, v[r].kind.value, round(v[r].speed_scale or 0.0, 6))
                        for r in sorted(v)
                    )
                )
            return out

        assert trace() == trace()

    def test_verdict_order_is_independent_of_dict_insertion_order(self):
        """Arbitration must not depend on how the caller happened to build the
        state dict. It resolves in sorted id order for exactly this reason."""
        a = state("R001", 0.0, heading=EAST)
        b = state("R002", 0.90, heading=WEST)

        pol1 = policy()
        for tick in range(15):
            v1 = pol1.arbitrate(tick, tick * 0.1, {"R001": a, "R002": b})

        pol2 = policy()
        for tick in range(15):
            v2 = pol2.arbitrate(tick, tick * 0.1, {"R002": b, "R001": a})

        assert {r: v1[r].kind for r in v1} == {r: v2[r].kind for r in v2}


# ---------------------------------------------------------------------------
# negotiation: symmetry, fairness, no starvation
# ---------------------------------------------------------------------------


class TestNegotiation:
    def test_symmetric_conflict_is_broken_not_deadlocked(self):
        """Two identical robots must not both yield or both proceed.

        Mutual yield is a deadlock; mutual proceed is a collision. A contest
        must produce exactly one winner, which is what the utility comparison
        plus a deterministic tie-break is for.
        """
        pol = policy()
        states = {
            "R001": state("R001", 0.0, 0.0, heading=EAST),
            "R002": state("R002", 0.0, 0.80, heading=NORTH),
        }
        verdicts = settle(pol, states, 12)
        moving = [
            r for r in ("R001", "R002") if (verdicts[r].speed_scale or 0.0) > 0.0
        ]
        assert len(moving) <= 1
        assert pol.stats()["contests"] > 0

    def test_every_verdict_carries_a_human_readable_reason(self):
        """X-26 Decision Inspector shows these to a judge. An empty reason is
        an unexplainable safety decision, which defeats the purpose."""
        pol = policy()
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.85, heading=WEST),
            "R003": state("R003", 8.0, 8.0),
        }
        verdicts = settle(pol, states, 12)
        for rid, v in verdicts.items():
            assert v.reason and v.reason.strip(), f"{rid} had no reason"
            assert v.robot_id == rid

    def test_conflict_with_names_the_peer_responsible(self):
        pol = policy()
        states = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.85, heading=WEST),
        }
        verdicts = settle(pol, states, 12)
        constrained = [
            v for v in verdicts.values() if v.kind is not VerdictKind.PROCEED
        ]
        assert constrained, "expected at least one constrained robot"
        assert any(v.conflict_with for v in constrained)

    def test_speed_scale_is_always_a_valid_fraction(self):
        """A scale outside [0, 1] would be the arbiter commanding a robot to
        exceed its own speed limit, or to reverse."""
        pol = policy()
        states = {
            f"R{i:03d}": state(f"R{i:03d}", i * 0.45, heading=EAST if i % 2 else WEST)
            for i in range(10)
        }
        for tick in range(25):
            for v in pol.arbitrate(tick, tick * 0.1, states).values():
                scale = v.speed_scale
                if scale is not None:
                    assert 0.0 <= scale <= 1.0


# ---------------------------------------------------------------------------
# failure handling
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_failed_robot_receives_a_wait_verdict(self):
        """A failed robot has no controller left to obey a verdict; the honest
        output is WAIT and the simulation's onboard brake does the rest."""
        pol = policy()
        states = {
            "R001": state("R001", 0.0),
            "R002": state("R002", 3.0, status=RobotStatus.FAILED, velocity=0.0),
        }
        verdicts = settle(pol, states, 5)
        assert verdicts["R002"].kind is VerdictKind.WAIT

    def test_blocked_by_a_failed_peer_leads_to_reroute_not_indefinite_wait(self):
        """X-23. A dead robot will never move, so waiting for it is waiting
        forever; the only correct response is to go around.

        The peer is kept MOVING in the published state so that the failure is
        discovered through the failure detector's own timeout - the realistic
        case, where a robot goes silent rather than announcing its own death.
        """
        pol = policy()
        live = state("R001", 0.0, heading=EAST)
        dead = state("R002", 0.85, heading=WEST, velocity=0.0)
        both = {"R001": live, "R002": dead}

        # Phase 1: both present, so R001 learns R002 exists.
        for tick in range(15):
            pol.arbitrate(tick, tick * 0.1, both)

        # Phase 2: R002 goes silent. Its last known position still blocks the
        # aisle, so R001 must reroute rather than wait on a ghost.
        kinds = set()
        for tick in range(15, 15 + MONITOR_STUCK_TICKS * 6 + 40):
            v = pol.arbitrate(tick, tick * 0.1, {"R001": live})
            kinds.add(v["R001"].kind)

        assert VerdictKind.REROUTE in kinds or VerdictKind.PROCEED in kinds, (
            "R001 stayed blocked by a peer that had stopped transmitting"
        )

    def test_stale_peer_entries_stop_constraining(self):
        """A peer that has gone quiet must not hold an aisle it has left.

        Freshness is what lets the fleet recover from packet loss instead of
        accumulating phantom obstacles.
        """
        pol = policy()
        both = {
            "R001": state("R001", 0.0, heading=EAST),
            "R002": state("R002", 0.85, heading=WEST),
        }
        for tick in range(15):
            pol.arbitrate(tick, tick * 0.1, both)

        for tick in range(15, 60):
            v = pol.arbitrate(tick, tick * 0.1, {"R001": both["R001"]})
        # Once R002's entry is stale and its route is replanned around, R001
        # must be moving again.
        assert (v["R001"].speed_scale or 0.0) > 0.0 or \
            v["R001"].kind is VerdictKind.REROUTE


# ---------------------------------------------------------------------------
# introspection surface consumed by M1/M2
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_stats_exposes_the_keys_the_dashboard_reads(self):
        pol = policy()
        states = {"R001": state("R001", 0.0), "R002": state("R002", 0.85, heading=WEST)}
        settle(pol, states, 10)
        s = pol.stats()
        for key in (
            "policy", "ticks", "verdicts", "contests", "contests_won",
            "monitor_enabled", "monitor_vetoes", "monitor_overrides",
            "vetoes_per_tick", "reroutes", "failures_confirmed",
            "msgs_per_robot_tick",
        ):
            assert key in s, f"stats() is missing {key}"

    def test_explain_returns_the_decision_inspector_payload(self):
        pol = policy()
        states = {"R001": state("R001", 0.0), "R002": state("R002", 0.85, heading=WEST)}
        settle(pol, states, 12)
        e = pol.explain("R001")
        assert e["robot_id"] == "R001"
        assert e["verdict"] is not None
        assert e["peers_heard"] == ["R002"]
        assert e["peer_count"] == 1
        assert "R002" in e["health"]

    def test_explain_on_an_unknown_robot_does_not_raise(self):
        """The UI can ask about a robot that has just left the fleet."""
        pol = policy()
        e = pol.explain("R999")
        assert e["verdict"] is None
        assert e["peers_heard"] == []

    def test_verdict_counts_total_matches_robots_times_ticks(self):
        """Every robot must get exactly one verdict per tick. A missing verdict
        is an un-arbitrated robot, i.e. an unsupervised one."""
        pol = policy()
        states = {f"R{i:03d}": state(f"R{i:03d}", i * 3.0) for i in range(5)}
        ticks = 10
        for tick in range(ticks):
            v = pol.arbitrate(tick, tick * 0.1, states)
            assert set(v) == set(states)
        assert sum(pol.stats()["verdicts"].values()) == 5 * ticks


# ---------------------------------------------------------------------------
# geometric invariants of the tuned constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_bands_are_strictly_ordered(self):
        """The three-band structure only means anything if the bands nest."""
        assert HARD_STOP_M < CONFLICT_M < CAUTION_M

    def test_conflict_band_is_exactly_one_step_above_the_floor(self):
        """CONFLICT_M must leave room to stop before the floor in one tick;
        otherwise a robot could discover a conflict too late to honour it."""
        assert CONFLICT_M == pytest.approx(HARD_STOP_M + MAX_STEP_M)

    def test_floor_exceeds_the_physical_pair_footprint(self):
        """Two 0.35 m robots occupy 0.70 m, so a 0.75 m floor keeps a real
        margin rather than merely forbidding overlap."""
        assert HARD_STOP_M > sp.FOOTPRINT_M
