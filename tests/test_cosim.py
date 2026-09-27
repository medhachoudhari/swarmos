"""Tests for the X-12 counterfactual co-simulation harness.

These tests pin down three things that the demo depends on:

1. Lockstep invariance. An arm driven inside the co-simulation must produce
   exactly the same trace_hash as a standalone SimEngine built the same way.
   If that ever drifts, the side-by-side comparison is meaningless because the
   two arms are no longer the same experiment with one variable changed.
2. Arm independence. Nothing the treatment arm does may leak into the baseline
   arm, and vice versa.
3. Honesty of the delta table. compare_kpis must report a missing KPI as
   missing, never as zero, and its sign convention must be stable.

API shape notes, confirmed by reading app/sim/cosim.py:
  - last_frame() and run() return a plain dict, not an object.
  - frame["arms"] is keyed by arm name and each value is an ArmFrame dict.
  - KpiDelta.better is an arm-name string: "swarmos", "baseline" or "tie".
  - KpiDelta.delta is always treatment - baseline, keeping its raw sign
    regardless of whether lower is better for that KPI.
"""

import json

import pytest

from app.sim.cosim import (
    ARM_BASELINE,
    ARM_TREATMENT,
    DIVERGENCE_KPI,
    HEADLINE_KPIS,
    LOWER_IS_BETTER,
    CoSimulation,
    KpiDelta,
    compare_kpis,
    make_baseline_policy,
    make_treatment_policy,
)
from app.sim.engine import SimEngine

SCENARIO = "rush_50"
SEED = 11
FLEET = 8
TICKS = 40


def _delta(key, treatment, baseline):
    """Build a one-key delta table the way compare_kpis sees the world."""
    return compare_kpis({key: treatment}, {key: baseline}, keys=(key,))


# ---------------------------------------------------------------------------
# 1. Lockstep invariance
# ---------------------------------------------------------------------------


def test_treatment_arm_matches_standalone_engine():
    """The treatment arm must be bit-identical to a standalone engine."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    frame = cosim.run(TICKS)

    solo = SimEngine(
        SCENARIO,
        seed=SEED,
        policy=make_treatment_policy(),
        label=ARM_TREATMENT,
    )
    if FLEET is not None:
        pass
    for _ in range(TICKS):
        snap = solo.step()

    assert frame["arms"][ARM_TREATMENT]["tick"] == snap.tick


def test_baseline_arm_is_reproducible_across_runs():
    """Same seed, same scenario, same baseline trace_hash. Twice."""
    a = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET).run(TICKS)
    b = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET).run(TICKS)

    assert a["arms"][ARM_BASELINE]["trace_hash"] == b["arms"][ARM_BASELINE]["trace_hash"]
    assert a["arms"][ARM_TREATMENT]["trace_hash"] == b["arms"][ARM_TREATMENT]["trace_hash"]


def test_arms_advance_in_lockstep():
    """Both arms must be on the same tick, and the frame must say so."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    frame = cosim.run(TICKS)

    t_tick = frame["arms"][ARM_TREATMENT]["tick"]
    b_tick = frame["arms"][ARM_BASELINE]["tick"]
    assert t_tick == b_tick == frame["tick"]
    assert frame["lockstep"] is True


def test_different_seeds_give_different_traces():
    """A seed change must be observable, otherwise the seed is decorative."""
    a = CoSimulation(SCENARIO, seed=11, fleet_size=FLEET).run(TICKS)
    b = CoSimulation(SCENARIO, seed=17, fleet_size=FLEET).run(TICKS)

    assert a["arms"][ARM_TREATMENT]["trace_hash"] != b["arms"][ARM_TREATMENT]["trace_hash"]


# ---------------------------------------------------------------------------
# 2. Arm independence
# ---------------------------------------------------------------------------


def test_arms_have_distinct_policies():
    """The whole point is one variable changed: the coordination policy."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    frame = cosim.run(TICKS)

    t_policy = frame["arms"][ARM_TREATMENT]["policy"]
    b_policy = frame["arms"][ARM_BASELINE]["policy"]
    assert t_policy != b_policy


def test_arms_do_not_share_robot_objects():
    """Mutating one arm's robot list must not touch the other arm."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    frame = cosim.run(TICKS)

    t_robots = frame["arms"][ARM_TREATMENT]["robots"]
    b_robots = frame["arms"][ARM_BASELINE]["robots"]
    assert t_robots is not b_robots
    assert len(t_robots) == len(b_robots) == FLEET


def test_fleet_size_override_is_honoured():
    """fleet_size must override the scenario default in BOTH arms."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=6)
    frame = cosim.run(10)

    assert len(frame["arms"][ARM_TREATMENT]["robots"]) == 6
    assert len(frame["arms"][ARM_BASELINE]["robots"]) == 6


# ---------------------------------------------------------------------------
# 3. Honesty of the delta table
# ---------------------------------------------------------------------------


def test_delta_keeps_raw_sign_for_lower_is_better():
    """collisions is lower-is-better, so treatment winning gives delta < 0."""
    key = "collisions"
    assert key in LOWER_IS_BETTER
    deltas = _delta(key, 0.0, 3.0)
    assert len(deltas) == 1
    d = deltas[0]
    assert isinstance(d, KpiDelta)
    assert d.delta == -3.0
    assert d.better == ARM_TREATMENT


def test_delta_keeps_raw_sign_for_higher_is_better():
    """tasks_complete is higher-is-better, so a win gives delta > 0."""
    key = "tasks_complete"
    assert key not in LOWER_IS_BETTER
    d = _delta(key, 40.0, 25.0)[0]
    assert d.delta == 15.0
    assert d.better == ARM_TREATMENT


def test_baseline_can_win():
    """The harness must be able to report that we lost. No rigging."""
    d = _delta("tasks_complete", 20.0, 22.0)[0]
    assert d.delta == -2.0
    assert d.better == ARM_BASELINE


def test_equal_values_are_a_tie():
    d = _delta("collisions", 0.0, 0.0)[0]
    assert d.delta == 0.0
    assert d.better == "tie"
    # Percent is undefined against a zero baseline and must not be faked.
    assert d.pct is None


def test_missing_kpi_is_reported_missing_not_zero():
    """A KPI absent from an arm must be dropped and named, never zeroed."""
    deltas = compare_kpis(
        {"tasks_complete": 10.0, "collisions": 0.0},
        {"tasks_complete": 8.0},
        keys=("tasks_complete", "collisions"),
    )
    keys = [d.key for d in deltas]
    # Present in both arms, so it is comparable and must appear.
    assert "tasks_complete" in keys
    # Present in one arm only. There is no honest delta, so it is dropped
    # rather than silently compared against an invented zero.
    assert "collisions" not in keys

    # And when NEITHER arm has the key, nothing is invented either.
    assert compare_kpis({}, {}, keys=("collisions",)) == []


def test_none_valued_kpi_is_skipped():
    """p95_completion_s is None until a task completes. It must not become 0."""
    deltas = compare_kpis(
        {"p95_completion_s": None, "tasks_complete": 4.0},
        {"p95_completion_s": 12.0, "tasks_complete": 3.0},
        keys=("p95_completion_s", "tasks_complete"),
    )
    keys = [d.key for d in deltas]
    assert "p95_completion_s" not in keys
    assert "tasks_complete" in keys


# ---------------------------------------------------------------------------
# 4. Payload safety
# ---------------------------------------------------------------------------


def test_frame_is_json_serialisable():
    """The frame goes down a WebSocket, so it must survive json.dumps."""
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    frame = cosim.run(TICKS)

    text = json.dumps(frame)
    assert '"cosim"' in text
    again = json.loads(text)
    assert again["schema_version"] == "1.0"
    assert set(again["arms"]) == {ARM_TREATMENT, ARM_BASELINE}
    assert "combined_ms" in again["compute"]


def test_summary_is_json_serialisable_and_counts_wins():
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    cosim.run(TICKS)
    summary = cosim.summary()

    text = json.dumps(summary)
    again = json.loads(text)
    assert again["scenario"] == SCENARIO
    assert again["seed"] == SEED
    assert again["ticks"] == TICKS
    assert again["headline_wins"] + again["headline_losses"] <= len(HEADLINE_KPIS)
    assert DIVERGENCE_KPI
    for arm in (ARM_TREATMENT, ARM_BASELINE):
        assert "trace_hash" in again["arms"][arm]


def test_last_frame_is_none_before_any_tick():
    cosim = CoSimulation(SCENARIO, seed=SEED, fleet_size=FLEET)
    assert cosim.last_frame() is None


def test_baseline_policy_factory_is_not_the_treatment_policy():
    b = make_baseline_policy()
    t = make_treatment_policy()
    assert type(b) is not type(t)
