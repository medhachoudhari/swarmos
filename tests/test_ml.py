"""M3 advisory layer tests.

The centre of this file is the law-3 proof: a deliberately hostile forecaster
must not change robot behaviour or the trace hash. Everything else supports it.
"""

from __future__ import annotations

import pytest

from app.coordination.swarm_policy import SwarmPolicy
from app.ml.budget import BUDGET_MS, BudgetMeter, Firewall, _percentile
from app.ml.forecast import (
    CAPACITY,
    HORIZON_TICKS,
    ZONE_M,
    Advisory,
    Forecaster,
    _slope,
    _xy,
    zone_of,
)
from app.sim.clock import TICK_BUDGET_MS
from app.sim.engine import SimEngine


class _Pos:
    """Minimal stand-in for the engine's Position (has .x/.y, no indexing)."""

    def __init__(self, x, y):
        self.x = x
        self.y = y


class _State:
    def __init__(self, rid, x, y):
        self.robot_id = rid
        self.position = _Pos(x, y)


def _fleet(n, x=1.0, y=1.0, step=0.05):
    return [_State(f"R{i:03d}", x + step * i, y) for i in range(n)]


# ----------------------------------------------------------------- geometry


def test_zone_of_bins_on_the_declared_pitch():
    assert zone_of(0.0, 0.0) == (0, 0)
    assert zone_of(ZONE_M - 0.01, ZONE_M - 0.01) == (0, 0)
    assert zone_of(ZONE_M, ZONE_M) == (1, 1)
    assert zone_of(2 * ZONE_M + 0.5, 0.0) == (2, 0)


def test_xy_accepts_a_position_object_not_just_a_tuple():
    # This is the regression guard for a real defect: the adapter used
    # getattr(pos, "x", pos[0]), whose default expression was evaluated
    # eagerly, so every AMRState raised TypeError and the forecaster silently
    # produced nothing for an entire run.
    assert _xy(_State("R001", 3.0, 4.0)) == (3.0, 4.0)
    assert _xy((3.0, 4.0)) == (3.0, 4.0)
    assert _xy(_Pos(3.0, 4.0)) == (3.0, 4.0)


def test_xy_refuses_nonsense_loudly():
    with pytest.raises(TypeError):
        _xy(object())


def test_slope_is_a_least_squares_fit():
    assert _slope([0.0, 1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert _slope([3.0, 2.0, 1.0, 0.0]) == pytest.approx(-1.0)
    assert _slope([5.0, 5.0, 5.0]) == pytest.approx(0.0)
    assert _slope([7.0]) == 0.0
    assert _slope([]) == 0.0


# ---------------------------------------------------------------- forecaster


def test_a_filling_zone_is_detected_before_it_is_full():
    fc = Forecaster()
    for t in range(20):
        fc.observe(_fleet(1 + t // 6), t)
    hot = [f for f in fc.forecast() if f.filling or f.congested]
    assert hot, "a monotonically filling zone must be flagged"


def test_an_emptied_zone_loses_its_stale_trend():
    fc = Forecaster()
    for t in range(15):
        fc.observe(_fleet(8), t)
    for t in range(15, 60):
        fc.observe([], t)
    for f in fc.forecast():
        assert f.occupancy == 0
        assert not f.congested


def test_a_static_fleet_produces_no_advisory():
    fc = Forecaster()
    fleet = _fleet(2)
    for t in range(40):
        fc.observe(fleet, t)
    assert fc.advise(fleet) == {}


def test_a_crowded_zone_advises_every_robot_in_it():
    fc = Forecaster()
    for t in range(30):
        fc.observe(_fleet(min(CAPACITY + 3, 1 + t)), t)
    fleet = _fleet(CAPACITY + 3)
    adv = fc.advise(fleet)
    assert len(adv) == len(fleet)
    for a in adv.values():
        assert isinstance(a, Advisory)
        assert a.kind == "SLOW"
        assert 0.0 <= a.confidence <= 1.0


def test_the_forecaster_is_deterministic():
    def run():
        fc = Forecaster()
        for t in range(40):
            fc.observe(_fleet(min(9, 1 + t // 4)), t)
        return [f.as_dict() for f in fc.forecast()]

    assert run() == run()


def _slow_ramp(fc):
    """Drive a zone that is filling but has NOT yet reached capacity.

    This is the only state in which a crossing can be predicted: a zone already
    at capacity has nothing left to forecast. Getting this wrong is what made
    the first version of the purity test assert against an empty list.
    """
    for t in range(30):
        fc.observe(_fleet(1 + t // 8), t)


def test_forecast_is_a_pure_read():
    # forecast() is called by the UI, the advisory path and stats() in the same
    # tick. If it recorded predictions, the accuracy sample set would grow with
    # the number of readers rather than the number of predictions made.
    fc = Forecaster()
    _slow_ramp(fc)
    for _ in range(5):
        fc.forecast()
    assert fc._pending == [], "forecast() must not record anything"


def test_remember_is_the_one_place_a_prediction_is_recorded():
    fc = Forecaster()
    _slow_ramp(fc)
    filling = [f for f in fc.forecast() if f.filling]
    assert filling, "the ramp must produce a predicted capacity crossing"
    fc.remember(fc.forecast())
    assert len(fc._pending) == len(filling)
    # Calling it again records again - it is explicit, so the caller owns the
    # count. advise() is the single call site in the engine path.
    fc.remember(fc.forecast())
    assert len(fc._pending) == 2 * len(filling)


def test_accuracy_reports_nothing_before_it_has_scored_anything():
    acc = Forecaster().accuracy()
    assert acc == {"samples": 0, "mae": None, "within_1": None}


def test_accuracy_scores_predictions_against_what_happened():
    fc = Forecaster()
    for t in range(80):
        fc.observe(_fleet(min(9, 1 + t // 3)), t)
        fc.advise(_fleet(min(9, 1 + t // 3)))
    acc = fc.accuracy()
    assert acc["samples"] > 0
    # No threshold is asserted. The forecaster is allowed to be inaccurate; it
    # is not allowed to hide it. A pass/fail bar here would tempt us to tune
    # the test instead of reporting the number.
    assert acc["mae"] >= 0.0
    assert 0.0 <= acc["within_1"] <= 1.0


def test_advisory_as_dict_matches_what_the_inspector_reads():
    a = Advisory("R001", "SLOW", "because", 0.5, (1, 2))
    d = a.as_dict()
    assert set(d) == {"kind", "reason", "confidence", "zone"}
    assert d["zone"] == [1, 2]


# -------------------------------------------------------------- budget meter


def test_the_budget_constant_tracks_the_clock():
    # budget.py deliberately does not import the clock, so this test is the
    # only thing stopping the two values from drifting apart.
    assert BUDGET_MS == TICK_BUDGET_MS


def test_an_unmeasured_meter_reports_nothing_rather_than_zero():
    s = BudgetMeter().stats()
    assert s["samples"] == 0
    for k in ("p50_ms", "p95_ms", "p99_ms", "max_ms", "headroom_pct"):
        assert s[k] is None, f"{k} must be None, not fake data"


def test_percentiles_are_values_we_actually_measured():
    vals = [1.0, 2.0, 3.0, 4.0, 100.0]
    for q in (0.0, 0.5, 0.95, 1.0):
        assert _percentile(vals, q) in vals


def test_overruns_are_counted_and_headroom_is_stated_against_p95():
    m = BudgetMeter(budget_ms=10.0)
    for i in range(9):
        m.record(i, 1.0)
    m.record(9, 50.0)
    s = m.stats()
    assert s["overruns"] == 1
    assert s["overrun_pct"] == pytest.approx(10.0)
    assert s["max_ms"] == pytest.approx(50.0)
    assert s["headroom_pct"] >= 0.0


def test_stage_timings_are_reported_with_an_injected_clock():
    ticks = iter([0.0, 0.0, 0.002, 0.002, 0.005, 0.010])
    m = BudgetMeter(clock=lambda: next(ticks))
    m.begin(0)
    with m.stage("kernel"):
        pass
    with m.stage("ml"):
        pass
    s = m.end()
    assert s.stages["kernel"] == pytest.approx(2.0)
    assert s.stages["ml"] == pytest.approx(3.0)
    assert m.stats()["samples"] == 1


def test_end_without_begin_does_not_explode():
    # An instrument must never be the thing that takes down a live demo.
    m = BudgetMeter()
    s = m.end()
    assert s.total_ms == 0.0


# ------------------------------------------------------------------ firewall


def test_silence_is_neither_agreement_nor_override():
    fw = Firewall()
    assert fw.record(None, "PROCEED") is False
    assert fw.advisories == 0
    assert fw.stats()["override_pct"] is None


def test_the_firewall_counts_overrides_and_names_them():
    fw = Firewall()
    fw.record("SLOW", "SLOW")
    assert fw.record("SLOW", "WAIT") is True
    fw.record("SLOW", "WAIT")
    s = fw.stats()
    assert (s["advisories"], s["agreements"], s["overrides"]) == (3, 1, 2)
    assert s["top_overrides"] == {"SLOW->WAIT": 2}
    assert "never in the safety path" in s["claim"]


# ---------------------------------------------- integration with the engine


def _run(ticks=300, seed=11, mutate=None):
    e = SimEngine("narrow_aisle_deadlock", seed=seed, policy=SwarmPolicy())
    if mutate is not None:
        mutate(e)
    last = None
    for _ in range(ticks):
        last = e.step()
    return e, last


def test_the_engine_publishes_real_advisory_numbers():
    e, snap = _run()
    a = snap.as_dict()["kpis"]["advisory"]
    assert a["errors"] == 0, f"the advisory layer is failing: {a['last_error']}"
    assert a["proposed"] > 0, "the ML layer must actually make proposals"
    assert a["overridden"] > 0, (
        "if the kernel never disagreed we would have no evidence it decides "
        "independently rather than rubber-stamping"
    )


def test_a_visible_verdict_carries_the_advisory_the_inspector_reads():
    e = SimEngine("narrow_aisle_deadlock", seed=11, policy=SwarmPolicy())
    found = None
    for _ in range(300):
        snap = e.step()
        for v in snap.as_dict()["verdicts"]:
            if v.get("advisory"):
                found = v
                break
        if found:
            break
    assert found is not None, "the Advisory row would render empty for the judges"
    assert set(found["advisory"]) == {"kind", "reason", "confidence", "zone"}
    assert found["advisory"]["reason"]


# ---- the law-3 proof -------------------------------------------------------


class _HostileForecaster:
    """A forecaster that is wrong, loud, and occasionally explodes.

    If architectural law 3 holds, substituting this for the real one cannot
    change a single robot's motion.
    """

    def __init__(self):
        self.calls = 0

    def observe(self, states, tick):
        self.calls += 1
        if self.calls % 7 == 0:
            raise RuntimeError("hostile forecaster failing on purpose")

    def advise(self, states):
        if self.calls % 3 == 0:
            raise ValueError("hostile forecaster failing on purpose")
        # Order every robot to do something the kernel must ignore.
        return {
            getattr(s, "robot_id"): Advisory(
                getattr(s, "robot_id"), "REROUTE", "nonsense", 1.0, (0, 0)
            )
            for s in states
        }

    def forecast(self):
        return []

    def accuracy(self):
        return {"samples": 0, "mae": None, "within_1": None}


def test_a_hostile_forecaster_cannot_change_the_trace_hash():
    """THE law-3 proof. Advisory means advisory."""
    _, clean = _run()

    def sabotage(e):
        e.forecaster = _HostileForecaster()

    _, hostile = _run(mutate=sabotage)

    assert hostile.trace_hash == clean.trace_hash, (
        "a broken ML layer changed the physical outcome, which means it is in "
        "the safety path and architectural law 3 is violated"
    )


def test_disabling_the_ml_layer_cannot_change_the_trace_hash():
    _, on = _run()

    def off(e):
        e.ml_enabled = False

    _, disabled = _run(mutate=off)
    assert disabled.trace_hash == on.trace_hash
    assert disabled.as_dict()["kpis"]["advisory"]["proposed"] == 0


def test_a_hostile_forecaster_cannot_change_the_safety_record():
    _, clean = _run()

    def sabotage(e):
        e.forecaster = _HostileForecaster()

    _, hostile = _run(mutate=sabotage)
    for key in ("collisions", "near_misses", "tasks_complete", "overlap_ticks"):
        assert hostile.kpis[key] == clean.kpis[key], key


def test_forecaster_failures_are_counted_not_hidden():
    # The inverse of the proof above: the layer is allowed to fail harmlessly,
    # but it is not allowed to fail invisibly. A swallowed exception that is not
    # counted reads exactly like "no congestion detected", which is the most
    # dangerous possible reading of a broken instrument.
    def sabotage(e):
        e.forecaster = _HostileForecaster()

    e, snap = _run(ticks=60, mutate=sabotage)
    a = snap.as_dict()["kpis"]["advisory"]
    assert a["errors"] > 0
    assert a["last_error"] and "purpose" in a["last_error"]


def test_the_ml_package_does_not_import_the_safety_kernel():
    """Law 3 made structural. If this fails, someone has created the coupling
    the whole design exists to prevent.

    The imports are read out of the parsed AST rather than by searching the
    text. A substring search also matches the docstrings that explain the rule,
    which is how the first version of this test failed on a file that was
    perfectly correct.
    """
    import ast as _ast
    import pathlib

    forbidden = ("app.coordination", "app.sim")
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "ml"
    files = sorted(root.glob("*.py"))
    assert files, "the ml package should not be empty"
    for f in files:
        tree = _ast.parse(f.read_text())
        imported: list[str] = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, _ast.ImportFrom) and node.module:
                imported.append(node.module)
        for mod in imported:
            for bad in forbidden:
                assert mod != bad and not mod.startswith(bad + "."), (
                    f"{f.name} imports {mod}, which puts the advisory layer "
                    "inside the safety path"
                )
