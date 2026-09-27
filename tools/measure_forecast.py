"""X-05 decision evidence: is the occupancy forecaster accurate enough to be
promoted from advisory-only to an input the planner trusts?

Promotion criterion, set BEFORE looking at the numbers so the bar cannot be
moved to fit the result:

  A forecast may steer routing only if it beats the trivial persistence
  baseline ("the zone will hold whatever it holds now") on mean absolute
  error by a clear margin - taken here as at least a 20 pct MAE reduction -
  on the SAME (zone, target tick) pairs. Anything less and the planner would
  be paying latency, complexity and a law-3 violation for a number it could
  have guessed for free.

Method. A shadow Forecaster is fed the identical per-tick robot positions the
engine feeds its own. Each tick we take forecast(), keep every zone that
predicts a capacity crossing inside the horizon (these are exactly the
predictions Forecaster.remember() would retain, so the sample set matches the
product's own accuracy() population), and record two competing numbers for the
same future tick:

  model       predicted_peak
  persistence current occupancy, held flat

At the target tick both are scored against the actual occupancy of that zone.
Identical pairs, identical horizon, so the comparison is apples to apples.

Usage: PYTHONPATH=. python3 tools/measure_forecast.py [ticks] [fleet] [scenario]
"""
import dataclasses
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.ml.forecast import Forecaster, zone_of
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SEEDS = (11, 13, 17)
MARGIN_PCT = 20.0          # pre-registered promotion bar


def occupancy(eng):
    counts = {}
    for r in eng.robots.values():
        px, py = r.position
        z = zone_of(px, py)
        counts[z] = counts.get(z, 0) + 1
    return counts


def one_seed(seed, ticks, fleet, scenario):
    scen = SCENARIOS[scenario]
    if fleet and fleet != scen.fleet_size:
        scen = dataclasses.replace(scen, fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy("swarmos", seed),
                    label="swarmos")

    shadow = Forecaster()
    horizon = shadow.horizon
    pending = []               # (target_tick, zone, model_peak, persist)
    model_err, pers_err = [], []
    history = {}               # tick -> {zone: count}

    for _ in range(ticks):
        eng.step()
        t = eng.tick
        counts = occupancy(eng)
        history[t] = counts
        shadow.observe(list(eng.robots.values()), t)

        # Score anything due at this tick, both arms against the same truth.
        still = []
        for target, zone, peak, pers in pending:
            if target <= t:
                actual = float(counts.get(zone, 0))
                model_err.append(abs(peak - actual))
                pers_err.append(abs(pers - actual))
            else:
                still.append((target, zone, peak, pers))
        pending = still

        for f in shadow.forecast():
            if f.ticks_to_capacity is not None:
                pending.append((t + horizon, f.zone, f.predicted_peak,
                                float(f.occupancy)))

    mean = lambda xs: (sum(xs) / len(xs)) if xs else None
    return {
        "seed": seed,
        "samples": len(model_err),
        "model_mae": mean(model_err),
        "pers_mae": mean(pers_err),
        "advisory": eng.advisory_stats(),
        "engine_accuracy": eng.forecaster.accuracy(),
        "zones": len(history.get(eng.tick, {})),
    }


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
    fleet = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    scenario = sys.argv[3] if len(sys.argv) > 3 else "rush_50"

    rows = [one_seed(s, ticks, fleet, scenario) for s in SEEDS]

    print(f"ticks={ticks} fleet={fleet} scenario={scenario} "
          f"horizon={Forecaster().horizon} bar={MARGIN_PCT:.0f}pct")
    head = (f"{'seed':>5} {'pairs':>7} {'model_mae':>10} {'persist_mae':>12} "
            f"{'adv_made':>9} {'override_pct':>13}")
    print(head)
    fmt = lambda v: "--" if v is None else f"{v:.3f}"
    for r in rows:
        adv = r["advisory"]
        print(f"{r['seed']:>5} {r['samples']:>7} {fmt(r['model_mae']):>10} "
              f"{fmt(r['pers_mae']):>12} {adv.get('proposed', 0):>9} "
              f"{str(adv.get('override_pct')):>13}")

    tot = sum(r["samples"] for r in rows)
    if tot == 0:
        print("\nNo zone ever predicted a capacity crossing in these runs, so")
        print("the forecaster produced ZERO scoreable predictions. A model with")
        print("no measurable accuracy cannot be promoted into the planner.")
        print("VERDICT: X-05 stays fenced as advisory-only.")
        return 0

    scored = [r for r in rows if r["samples"] > 0]
    m = sum(r["model_mae"] * r["samples"] for r in scored) / tot
    p = sum(r["pers_mae"] * r["samples"] for r in scored) / tot
    gain = (p - m) / p * 100.0 if p else 0.0
    print(f"\npairs scored          {tot}")
    print(f"model MAE             {m:.3f} robots per zone")
    print(f"persistence MAE       {p:.3f} robots per zone")
    print(f"MAE reduction         {gain:+.1f} pct  (bar {MARGIN_PCT:.0f} pct)")
    if gain >= MARGIN_PCT:
        print("VERDICT: clears the pre-registered bar on accuracy alone.")
    else:
        print("VERDICT: fails the pre-registered bar. X-05 stays advisory-only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
