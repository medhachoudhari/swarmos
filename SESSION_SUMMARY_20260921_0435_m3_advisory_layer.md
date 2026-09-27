# M3 advisory layer complete - 2026-09-21 04:35

## Gates

| Gate | Result |
|---|---|
| Full pytest suite | **458 passed in 33.58 s** (was 429; +29 new, 0 regressions) |
| `tools/verify_frontend.py` | 10 js files, 43 html ids, 88 tokens, **0 errors / 0 warnings** |
| `tools/smoke_server.py` (real uvicorn, port 8781) | **SMOKE PASSED: every check green**, exit 0 |

## What was built

- **`app/ml/forecast.py`** - X-20 congestion forecaster. Zone occupancy history
  (4 m zones, 30-tick window) with a hand-written least-squares slope
  extrapolated 20 ticks ahead. Emits `Advisory{kind, reason, confidence, zone}`,
  exactly the shape `web/js/panels/inspector.js` already reads.
- **`app/ml/budget.py`** - X-04 compute budget meter (nearest-rank percentiles,
  headroom stated against p95, overruns counted, injectable clock) plus the
  `Firewall` override counter.
- **`app/ml/__init__.py`** - package exports.
- **`app/sim/engine.py`** - the advisory is computed before arbitration, attached
  to verdict dicts at the display boundary only, and published under
  `kpis.advisory`. The kernel is never shown it.
- **`tests/test_ml.py`** - 29 tests, including the law-3 proof.

## Measured: architectural law 3 is now evidence, not an assertion

From `narrow_aisle_deadlock`, seed 11, 300 ticks:

```
proposed 38, agreed 7, overridden 31 (81.6%)
top overrides: SLOW->PROCEED 20, SLOW->YIELD 6, SLOW->WAIT 3, SLOW->REROUTE 2
forecast accuracy: samples 9, mae 3.605, within_1 0.0
```

Two numbers matter and both are real:

1. **The kernel overrode the ML layer 81.6% of the time.** If it had never
   disagreed we would have no evidence it decides independently rather than
   rubber-stamping a prediction.
2. **The trace hash is byte-identical** (`0cd158c52e31497f`) with the forecaster
   live, with it disabled, and with a deliberately hostile forecaster
   substituted in. Proven by three tests, not claimed.

**The forecast accuracy is bad and is reported anyway: MAE 3.6 robots, 0% within
1.** That is the honest number for a linear fit on 3 s of data in a 24-robot
deadlock scenario. It is reported because a forecaster that cannot be shown to be
wrong is not evidence of anything, and because the accuracy number is precisely
why the ML layer is advisory in the first place. If asked on stage: this is the
argument for the architecture, not against it.

## Defect found: the ML layer was crashing on every single tick

`_xy()` was written as `getattr(pos, "x", pos[0])`. Python evaluates a default
argument *before* calling `getattr`, so `pos[0]` ran unconditionally and raised
`TypeError` on the `Position` dataclass - which has `.x` but is not
subscriptable. The permissive fallback rejected the only caller that mattered.

It surfaced as `proposed: 0`, i.e. **"no congestion detected"** - an instrument
failing 100% of the time that looked like good news. `_advise()` caught the
exception and dropped it silently.

Two fixes, and the second is the more important one:
- `_xy` now tests each branch explicitly and raises loudly on real nonsense.
- **The swallow is now counted.** `ml_errors` / `ml_last_error` are published in
  `kpis.advisory`, so a degraded advisory layer reads as degraded instead of
  quiet. `test_forecaster_failures_are_counted_not_hidden` locks this in.

> **Lesson worth keeping:** an exception that is swallowed *and uncounted* is
> indistinguishable from a quiet tick. For an instrument, that is the worst
> failure mode available - it fails towards reassurance.

## Second gap: only agreed-with advisories would have been visible

Snapshots filter out `PROCEED` verdicts as noise. But `SLOW->PROCEED` was 20 of
the 31 overrides - the clearest demonstration of independence - so the Inspector
would only ever have shown advisories the kernel *agreed* with, misrepresenting
the firewall as a rubber stamp. `_verdict_payload()` now keeps a PROCEED that
rejected an advisory, and synthesises a row for a robot the ML layer had an
opinion about that the kernel did not rule on.

## Two test bugs, mine not the code's

- The law-3 import check searched file text for `"app.coordination"` and matched
  the docstring *explaining the rule*. Now parses the AST and inspects actual
  import nodes.
- The purity test's ramp hit the fleet cap immediately, so no zone was ever
  "filling" (a zone already at capacity has no crossing to predict) and the
  assertion ran against an empty list. Split into two tests with a slower ramp.

## Unchanged: the honest performance position

SWARMOS still loses throughput to a tuned baseline by ~28%, collision-free
(baseline 29 completions vs 21). Nothing this leg touched that. Lead with N3
deterministic replay, N5 Simplex runtime assurance, N9 adversarial containment,
N10 counterfactual co-simulation, bounded-radio O(k) scaling, and the arbiter's
perfect safety record - now joined by a *measured* advisory firewall.

## Next

1. Remaining M4: gossip reservation GC via `FailureDetector.confirmed_failed()`,
   X-01 Sovereign Agent Mode, X-10 rogue quarantine with HMAC-signed messages,
   `tests/test_race_condition.py`.
2. X-12 counterfactual ghost fleet.
3. Evidence run via `app/db/benchmark.run_ab` over >= 10 seeds with a paired CI,
   reported against a TUNED baseline.
4. `run.sh` + README + master specification deck.
