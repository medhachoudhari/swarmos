"""M6 tests - persistence, replay traces and the statistics behind the claim.

These tests exist to protect three things that are easy to get quietly wrong:

  1. The database must be able to reconstruct a run from its own rows. If a
     chart can be drawn from memory but not from the store, the store is
     decoration.
  2. A trace must remain readable after a crash, and two traces of the same
     seed must be identical. That pair of properties is the whole of X-22/X-27.
  3. The verdict ladder in stats.py must refuse to say MET unless the lower
     bound of the confidence interval actually clears the target. A test that
     only checks the mean would let the project publish a claim it has not
     earned, so every rung of the ladder is asserted here.

Runtime is kept low by shrinking the fleet and the map rather than the tick
count, because tick count is what the determinism and decimation assertions
depend on.
"""

from __future__ import annotations

import dataclasses
import math
import os

import pytest

from app.db import (
    MIN_SEEDS,
    RunStore,
    TraceRecorder,
    confidence_interval_95,
    diff_traces,
    paired,
    read_trace,
    replay,
    trace_path,
    verify_determinism,
)
from app.db.stats import PairedComparison, percentile, stdev
from app.sim import SimEngine, StopAndWaitPolicy
from app.sim.scenarios import get_scenario


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def small_scenario(name: str = "rush_50", *, fleet: int = 6):
    """A cheap variant of a real scenario, so tests exercise the real code.

    Shrinking the fleet and the floor keeps each engine well under a second
    while leaving every code path - dispatch, planning, arbitration, service -
    on exactly the same implementation the demo uses.
    """
    base = get_scenario(name)
    return dataclasses.replace(
        base, fleet_size=fleet, width=24, height=16, task_rate_per_s=1.0,
    )


def run_engine(ticks: int = 40, *, seed: int = 11, fleet: int = 6):
    eng = SimEngine(small_scenario(fleet=fleet), seed=seed,
                    policy=StopAndWaitPolicy(), label="test")
    snaps = [eng.step() for _ in range(ticks)]
    return eng, snaps


# ----------------------------------------------------------------------
# RunStore round trip
# ----------------------------------------------------------------------
def test_store_round_trip_reconstructs_the_run():
    eng, snaps = run_engine(40)
    with RunStore(":memory:") as store:
        rid = store.start_run(
            scenario="rush_50", label="test", policy=eng.policy.name,
            seed=eng.seed, fleet_size=eng.scenario.fleet_size,
        )
        for snap in snaps:
            store.record_snapshot(rid, snap)
            if snap.events:
                store.record_events(rid, snap.events)
        store.record_tasks(rid, eng)
        store.record_violations(rid, eng.violations)
        kpis = eng.kpis()
        store.finish_run(
            rid, ticks=eng.clock.tick, sim_time_s=eng.sim_time,
            trace_hash=eng.trace_hash, kpis=kpis, messages_total=1234,
        )

        row = store.get_run(rid)
        assert row is not None
        assert row["trace_hash"] == eng.trace_hash
        assert row["seed"] == eng.seed
        # The KPI row must agree with the engine, not merely exist.
        assert row["tasks_complete"] == kpis["tasks_complete"]
        assert row["collisions"] == kpis["collisions"]
        assert store.violation_count(rid) == len(eng.violations)
        assert len(store.series(rid)) > 0
        assert rid in [r["run_id"] for r in store.list_runs(scenario="rush_50")]


def test_msgs_per_robot_tick_is_derived_not_assumed():
    """X-03 denominator sanity: the per-robot-per-tick rate must be exact."""
    with RunStore(":memory:") as store:
        rid = store.start_run(
            scenario="rush_50", label="test", policy="stop_and_wait",
            seed=1, fleet_size=5,
        )
        store.finish_run(
            rid, ticks=100, sim_time_s=10.0, trace_hash="h",
            kpis={"tasks_complete": 0, "robots_total": 5}, messages_total=1000,
        )
        # 1000 messages / (100 ticks * 5 robots) = 2.0
        assert store.get_run(rid)["msgs_per_robot_tick"] == pytest.approx(2.0)


def test_snapshots_are_decimated_not_written_every_tick():
    """Persistence must never be the reason a 100 ms tick is missed."""
    eng, snaps = run_engine(25)
    with RunStore(":memory:") as store:
        rid = store.start_run(
            scenario="rush_50", label="test", policy="p", seed=1, fleet_size=6,
        )
        written = [store.record_snapshot(rid, s, every=10) for s in snaps]
        # The first snapshot is tick 0, which is a boundary, so 0, 10 and 20 are
        # stored and the remaining 22 are skipped. Keeping tick 0 is deliberate:
        # a chart with no opening sample starts mid-air.
        assert sum(written) == 3
        assert [r["tick"] for r in store.series(rid)] == [0, 10, 20]


        # force= exists so a final tick is never lost to decimation.
        assert store.record_snapshot(rid, snaps[-1], every=10, force=True)


def test_completion_times_match_the_engine():
    eng, snaps = run_engine(120)
    with RunStore(":memory:") as store:
        rid = store.start_run(
            scenario="rush_50", label="test", policy="p", seed=11, fleet_size=6,
        )
        n = store.record_tasks(rid, eng)
        assert n == len(eng.completed)
        stored = sorted(store.completion_times(rid))
        engine_side = sorted(
            eng.tasks[t].completion_time_s for t in eng.completed
            if eng.tasks[t].completion_time_s is not None
        )
        assert stored == pytest.approx(engine_side)


def test_event_counts_group_by_kind():
    eng, snaps = run_engine(60)
    with RunStore(":memory:") as store:
        rid = store.start_run(
            scenario="rush_50", label="test", policy="p", seed=11, fleet_size=6,
        )
        total = 0
        for snap in snaps:
            if snap.events:
                total += store.record_events(rid, snap.events)
        counts = store.event_counts(rid)
        assert sum(counts.values()) == total
        if total:
            assert all(isinstance(k, str) and v > 0 for k, v in counts.items())


# ----------------------------------------------------------------------
# traces: crash survival and determinism
# ----------------------------------------------------------------------
def test_trace_round_trip_is_clean_and_replayable(tmp_path):
    eng, snaps = run_engine(30)
    path = str(tmp_path / "run.ndjson")
    rec = TraceRecorder(path, run_id="r1", static=eng.static_payload())
    for snap in snaps:
        rec.record(snap)
    rec.close(kpis=eng.kpis(), trace_hash=eng.trace_hash)

    summary = read_trace(path)
    assert summary.clean
    assert not summary.truncated
    assert summary.corrupt_lines == 0
    assert summary.ticks == len(snaps)
    assert summary.final_hash == eng.trace_hash
    assert summary.run_id == "r1"

    ticks = [r["tick"] for r in replay(path)]
    assert ticks == [s.tick for s in snaps]


def test_truncated_trace_is_reported_not_silently_accepted(tmp_path):
    """Simulates kill -9: the prefix must still parse and say it is partial."""
    eng, snaps = run_engine(30)
    path = str(tmp_path / "crash.ndjson")
    rec = TraceRecorder(path, run_id="r2", static=eng.static_payload(),
                        flush_every=1)
    for snap in snaps:
        rec.record(snap)
    rec._fh.flush()

    # Cut the file mid-line, exactly as a kill during a write would.
    size = os.path.getsize(path)
    with open(path, "r+") as fh:
        fh.truncate(size - 40)

    summary = read_trace(path)
    assert summary.truncated is True          # no footer was ever written
    assert summary.clean is False
    assert 0 < summary.ticks <= len(snaps)    # the prefix is still usable
    assert summary.run_id == "r2"


def test_identical_seeds_produce_identical_traces(tmp_path):
    spec = small_scenario()
    paths = []
    for i in range(2):
        eng = SimEngine(spec, seed=7, policy=StopAndWaitPolicy())
        p = str(tmp_path / f"t{i}.ndjson")
        rec = TraceRecorder(p, run_id=f"r{i}", static=eng.static_payload())
        for _ in range(40):
            rec.record(eng.step())
        rec.close(kpis=eng.kpis(), trace_hash=eng.trace_hash)
        paths.append(p)

    assert diff_traces(*paths) is None


def test_diff_traces_names_the_exact_divergent_tick(tmp_path):
    """The check must be able to FAIL, and say where, or it proves nothing."""
    spec = small_scenario()
    paths = []
    for i, seed in enumerate((7, 8)):
        eng = SimEngine(spec, seed=seed, policy=StopAndWaitPolicy())
        p = str(tmp_path / f"d{i}.ndjson")
        rec = TraceRecorder(p, run_id=f"r{i}", static=eng.static_payload())
        for _ in range(40):
            rec.record(eng.step())
        rec.close(kpis=eng.kpis(), trace_hash=eng.trace_hash)
        paths.append(p)

    diff = diff_traces(*paths)
    assert diff is not None
    assert diff["reason"] == "state hash diverged"
    assert isinstance(diff["tick"], int)
    assert diff["hash_a"] != diff["hash_b"]


def test_verify_determinism_builds_two_independent_engines():
    out = verify_determinism(
        small_scenario(), seed=11, ticks=60,
        policy_factory=StopAndWaitPolicy,
    )
    assert out["deterministic"] is True
    assert out["first_divergent_tick"] is None
    assert out["hash_a"] == out["hash_b"]


def test_trace_path_honours_compression_suffix():
    assert trace_path("abc").endswith("abc.ndjson")
    assert trace_path("abc", compress=True).endswith("abc.ndjson.gz")


def test_gzip_trace_is_transparent(tmp_path):
    eng, snaps = run_engine(12)
    path = str(tmp_path / "z.ndjson.gz")
    rec = TraceRecorder(path, run_id="rz", static=eng.static_payload())
    for snap in snaps:
        rec.record(snap)
    rec.close(kpis=eng.kpis(), trace_hash=eng.trace_hash)
    assert read_trace(path).ticks == len(snaps)


# ----------------------------------------------------------------------
# statistics: the ladder that guards the >=20% claim
# ----------------------------------------------------------------------
def _cmp(baseline, treatment, *, seeds=None) -> PairedComparison:
    seeds = seeds or tuple(range(len(baseline)))
    return PairedComparison(
        metric="avg_completion_s", seeds=tuple(seeds),
        baseline=tuple(baseline), treatment=tuple(treatment),
    )


def test_confidence_interval_is_infinite_below_two_samples():
    """One seed is not evidence, and the interval must say so, not imply zero."""
    ci = confidence_interval_95([5.0])
    assert ci.n == 1
    assert math.isinf(ci.half_width)
    assert ci.low == -math.inf and ci.high == math.inf
    assert ci.excludes_zero is False


def test_delta_sign_convention_positive_means_improvement():
    c = _cmp([100.0] * 10, [80.0] * 10)
    assert all(d == pytest.approx(20.0) for d in c.deltas)
    assert all(p == pytest.approx(20.0) for p in c.deltas_pct)
    assert c.wins == 10


def test_zero_baseline_seeds_are_skipped_in_percentages():
    c = _cmp([0.0, 100.0, 100.0], [0.0, 80.0, 80.0])
    # Three seeds in, two percentages out: no infinite improvement is invented.
    assert len(c.deltas) == 3
    assert len(c.deltas_pct) == 2


def test_verdict_insufficient_data_below_min_seeds():
    c = _cmp([100.0] * 3, [50.0] * 3)          # a huge but unproven win
    v = c.verdict()
    assert v["status"] == "INSUFFICIENT_DATA"
    assert v["claim_supported"] is False
    assert v["seeds_required"] == MIN_SEEDS


def test_verdict_not_significant_when_interval_straddles_zero():
    base = [100.0] * 10
    treat = [60, 140, 70, 130, 90, 110, 80, 120, 95, 105]
    c = _cmp(base, [float(t) for t in treat])
    v = c.verdict()
    assert v["status"] == "NOT_SIGNIFICANT"
    assert v["claim_supported"] is False
    assert c.interval_pct().low < 0.0 < c.interval_pct().high


def test_verdict_significant_below_target_is_not_dressed_up_as_met():
    """A real 10% win must never be reported as meeting a 20% target."""
    base = [100.0] * 10
    treat = [90.0, 91.0, 89.0, 90.5, 89.5, 90.0, 91.0, 89.0, 90.0, 90.0]
    c = _cmp(base, treat)
    v = c.verdict()
    assert v["status"] == "SIGNIFICANT_BELOW_TARGET"
    assert v["significant"] is True
    assert v["claim_supported"] is False


def test_verdict_met_requires_the_lower_bound_to_clear_the_target():
    base = [100.0] * 10
    treat = [70.0, 71.0, 69.0, 70.5, 69.5, 70.0, 71.0, 69.0, 70.0, 70.0]
    c = _cmp(base, treat)
    ci = c.interval_pct()
    v = c.verdict()
    assert v["status"] == "MET"
    assert v["claim_supported"] is True
    assert ci.low >= c.target_pct        # this, not the mean, is the gate


def test_mean_above_target_but_wide_interval_is_refused():
    """The decisive test: mean beats 20%, lower bound does not, verdict is honest."""
    base = [100.0] * 10
    treat = [40.0, 100.0, 50.0, 95.0, 60.0, 90.0, 55.0, 98.0, 65.0, 92.0]
    c = _cmp(base, treat)
    ci = c.interval_pct()
    assert ci.mean > 20.0                # the headline number looks great
    assert ci.low < 20.0                 # the evidence does not support it
    assert c.verdict()["status"] == "SIGNIFICANT_BELOW_TARGET"


def test_paired_sorts_seeds_so_reports_are_byte_stable():
    c = paired("avg_completion_s", {29: (100.0, 80.0), 11: (90.0, 70.0)})
    assert c.seeds == (11, 29)
    assert c.baseline == (90.0, 100.0)


def test_render_and_as_dict_are_serialisable():
    c = _cmp([100.0] * 10, [80.0] * 10)
    text = c.render()
    assert "verdict" in text and "improvement" in text
    d = c.as_dict()
    assert d["verdict"]["status"] == "MET"
    assert d["metric"] == "avg_completion_s"
    assert len(d["seeds"]) == 10


def test_percentile_matches_engine_nearest_rank():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(xs, 0.0) == 1.0
    assert percentile(xs, 1.0) == 5.0
    assert percentile([], 0.5) is None


def test_stdev_uses_bessel_correction():
    # Sample standard deviation of [2, 4, 4, 4, 5, 5, 7, 9] is 2.1380..., the
    # population figure is 2.0. Getting this wrong narrows every interval.
    xs = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert stdev(xs) == pytest.approx(2.13809, abs=1e-4)


# ----------------------------------------------------------------------
# benchmark harness
# ----------------------------------------------------------------------
def test_run_one_persists_and_returns_metrics():
    from app.db.benchmark import run_one

    with RunStore(":memory:") as store:
        arm = run_one(
            small_scenario(), seed=11, ticks=40, label="swarmos",
            policy_factory=StopAndWaitPolicy, store=store,
        )
        assert arm.run_id is not None
        assert arm.ticks == 40
        assert arm.trace_hash
        assert store.get_run(arm.run_id)["trace_hash"] == arm.trace_hash
        assert arm.metric("collisions") == 0


def test_run_ab_excludes_and_names_barren_seeds():
    """A seed with no completed tasks must be excluded WITH its reason stated."""
    from app.db.benchmark import run_ab
    from app.sim import NoOpPolicy

    result = run_ab(
        small_scenario(), baseline_factory=NoOpPolicy,
        treatment_factory=StopAndWaitPolicy, seeds=(11, 13), ticks=40,
    )
    assert result.seeds == (11, 13)
    # 40 ticks is four simulated seconds, far too short to finish a task, so
    # every seed should be excluded and every exclusion should carry a reason.
    for seed in result.excluded_seeds:
        assert isinstance(result.excluded_seeds[seed], str)
        assert result.excluded_seeds[seed]
    assert set(result.usable_seeds) == set(result.seeds) - set(result.excluded_seeds)

    summary = result.safety_summary()
    assert summary["treatment_collisions"] == 0
    assert "baseline_collisions" in summary
    assert isinstance(result.render(), str)

# File contains AI-generated response based on internal company sources
