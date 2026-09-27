# X-05 decision: the occupancy forecaster stays advisory-only

**Status: DECIDED - not promoted. Fenced by `tests/test_ml_fence.py`.**
**Date: 2026-09-21. Evidence: `tools/measure_forecast.py`.**

## The question

SWARMOS contains an occupancy forecaster (`app/ml/forecast.py`). It divides the
warehouse into zones, fits a slope to recent occupancy, and extrapolates 20
ticks (2 seconds) ahead to predict which zones are about to fill.

X-05 asked whether that prediction is good enough to be promoted from
*advisory* (shown to the operator, proposed to the arbiter, freely overridden)
to *authoritative* (an input the planner trusts when choosing routes).

## The bar, registered before measuring

From the docstring of `tools/measure_forecast.py`, written before any number
was read:

> A forecast may steer routing only if it beats the trivial persistence
> baseline ("the zone will hold whatever it holds now") on mean absolute error
> by a clear margin - taken here as at least a 20 pct MAE reduction - on the
> SAME (zone, target tick) pairs. Anything less and the planner would be paying
> latency, complexity and a law-3 violation for a number it could have guessed
> for free.

Persistence is the right control. It is free, it needs no model, no history and
no compute, and any forecaster that cannot beat it is adding risk for nothing.

## Method

A shadow `Forecaster` is fed exactly the per-tick robot positions the engine
feeds its own. Every tick, each zone whose forecast predicts a capacity
crossing inside the horizon is recorded twice for the same future tick:

| arm | prediction |
|---|---|
| model | `predicted_peak` (current + slope * horizon) |
| persistence | current occupancy, held flat |

At the target tick both are scored against the actual occupancy of that zone.
Identical zones, identical target ticks, identical horizon, so the comparison
is apples to apples. The retained-prediction population is the same one
`Forecaster.remember()` uses, so this measures the product's own accuracy
population and not a friendlier one.

## Result

Scenario `rush_50`, 1800 ticks (180 s of sim time, well past the startup
transient), seeds 11 / 13 / 17.

| fleet | pairs scored | model MAE | persistence MAE | MAE reduction | verdict |
|---|---|---|---|---|---|
| 8 | 27 | 5.344 | 0.667 | **-701.6 pct** | fails |
| 50 | 224 | 2.308 | 0.415 | **-456.0 pct** | fails |

The model is not marginally worse. It is **five to eight times worse** than
doing nothing, at both a sparse and a dense fleet, on every seed that produced
a scoreable prediction.

## Why it fails

The forecaster fits a straight line to recent occupancy and extends it 20
ticks. Robot flow through a warehouse aisle is bursty, not linear: a zone fills
as a group arrives and empties as the group leaves. A slope measured during the
arrival is extrapolated straight through the departure, so `predicted_peak`
overshoots by several robots. Persistence has no slope to be wrong about, so it
cannot overshoot.

This is a property of the estimator, not a tuning accident. Shrinking the
horizon would reduce the error only by making the forecast converge on
persistence, which is the same as admitting persistence wins.

## Decision

1. **The forecaster is not promoted.** It remains advisory: displayed,
   proposed, and freely overridden by the M4 arbiter. This was already the
   architecture (law 3: ML is advisory only, never in the safety path); X-05
   confirms it is also the *correct* architecture on the numbers, not merely a
   conservative default.
2. **The fence is now structural**, in `tests/test_ml_fence.py`:
   - `app/coordination/**` must not import `app/ml` at all. An import is the
     weakest possible coupling and is still forbidden, so no reviewer has to
     reason about whether a particular call site is in the safety path.
   - every advisory is counted as either agreed or overridden, so the override
     path is observable rather than assumed;
   - a deliberately exploding forecaster is injected and the fleet must keep
     running. Anything in the safety path that throws must halt the fleet; the
     fact that this one does not is the evidence it is outside.
3. **The numbers are reported, not hidden.** The UI already labels ML output as
   advisory and shows the live override percentage (94-96 pct at fleet 50), so
   an operator can see for themselves how often the arbiter disagrees.

## What to say if a judge asks "where is your AI?"

The honest answer, which is stronger than a claim:

> We built the forecaster, then measured it against the cheapest possible
> baseline and it lost by 4x. So we did not let it drive. It advises, the
> safety kernel decides, and we show you the disagreement rate live. The part
> of this system you should trust is the part we could prove: deterministic
> replay, the Simplex safety kernel, and rogue-robot containment.

A team that can show a negative result about its own model has demonstrated
engineering judgement. A team that quietly wires an unvalidated model into the
collision-avoidance path has demonstrated the opposite.

## Reproduce

```
PYTHONPATH=. python3 tools/measure_forecast.py 1800 8  rush_50
PYTHONPATH=. python3 tools/measure_forecast.py 1800 50 rush_50
```
