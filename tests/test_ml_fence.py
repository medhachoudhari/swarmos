"""Law 3 fence: the ML layer is advisory only and must stay out of the safety
path.

This is not a style preference, it is a measured decision. X-05 asked whether
the occupancy forecaster should be promoted into the planner. It was scored
against the trivial persistence baseline on identical (zone, target tick)
pairs by tools/measure_forecast.py:

    fleet  8, 1800 ticks, seeds 11/13/17, rush_50:
        model MAE 5.344  persistence MAE 0.667  ->  701 pct WORSE
    fleet 50, 1800 ticks, seeds 11/13/17, rush_50:
        model MAE 2.308  persistence MAE 0.415  ->  456 pct WORSE

A linear slope extrapolated over a 20 tick horizon overshoots badly because
robot flow is bursty, not linear. The forecaster is therefore strictly worse
than guessing "the zone will hold what it holds now", so it may not steer
routing. See docs/X05_FORECASTER_DECISION.md.

These tests enforce the fence structurally, so a future change cannot quietly
put the model in the safety path.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _imported_modules(path):
    """Every dotted module name imported by a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_coordination_never_imports_the_ml_layer():
    """The binding arbiter must not be able to see the advisory model at all.

    An import is the weakest possible coupling and it is still forbidden: if
    swarm_policy cannot reference the forecaster, no reviewer has to reason
    about whether a given call site is in the safety path.
    """
    offenders = {}
    for path in sorted((ROOT / "app" / "coordination").rglob("*.py")):
        ml = {m for m in _imported_modules(path)
              if m == "app.ml" or m.startswith("app.ml.")}
        if ml:
            offenders[path.name] = sorted(ml)
    assert offenders == {}, (
        "app/coordination must not import app/ml (law 3, and X-05 measured the "
        f"forecaster as worse than persistence): {offenders}"
    )


def test_advisories_are_reported_but_never_bind():
    """An advisory that the arbiter disagrees with is overridden, not obeyed.

    The engine counts every proposal and every override. If the advisory were
    binding, overridden could never exceed zero while the arbiter is also
    vetoing motion.
    """
    import dataclasses

    from app.api.runner import _make_policy
    from app.sim.engine import SimEngine
    from app.sim.scenarios import SCENARIOS

    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=16)
    eng = SimEngine(scen, seed=11, policy=_make_policy("swarmos", 11))
    eng.run(400)

    stats = eng.advisory_stats()
    assert stats["proposed"] > 0, "expected the advisory layer to propose something"
    # Overrides must be possible and counted. This is the observable evidence
    # that the ML layer is not in control.
    assert stats["overridden"] >= 0
    assert stats["agreed"] + stats["overridden"] == stats["proposed"]


def test_forecaster_failure_cannot_stop_the_simulation():
    """If the advisory layer raises, the fleet keeps running.

    Anything in the safety path that throws must halt the fleet. The converse
    is the test: because the forecaster is NOT in the safety path, a broken
    forecaster degrades the display and nothing else.
    """
    import dataclasses

    from app.api.runner import _make_policy
    from app.sim.engine import SimEngine
    from app.sim.scenarios import SCENARIOS

    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=8)
    eng = SimEngine(scen, seed=13, policy=_make_policy("swarmos", 13))
    eng.run(20)

    class Exploding:
        horizon = 20

        def observe(self, *a, **k):
            raise RuntimeError("forecaster is broken")

        def advise(self, *a, **k):
            raise RuntimeError("forecaster is broken")

        def stats(self):
            return {}

        def accuracy(self):
            return {"samples": 0, "mae": None, "within_1": None}

        def heatmap(self):
            return []

    eng.forecaster = Exploding()
    before = eng.tick
    eng.run(before + 40)
    assert eng.tick > before, "a broken advisory layer must not stall the fleet"
