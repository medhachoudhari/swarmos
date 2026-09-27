"""Measure PRIORITY_ORDER against a FAIRLY TUNED baseline.

The baseline runs at STUCK_TICKS = 8, which diag_baseline_sweep.py showed to be
its own collision-free optimum (29 completions). Comparing against its untuned
default of 30 is what produced this session's false "+5.3% win", and is not
repeated here.
"""
import dataclasses
import random
import sys

sys.path.insert(0, ".")

from app.coordination import swarm_policy as sp       # noqa: E402
from app.sim.engine import SimEngine                  # noqa: E402
from app.sim.policy import StopAndWaitPolicy          # noqa: E402
from app.sim.scenarios import get_scenario            # noqa: E402

TICKS = 900
SEEDS = (11, 13, 17)
FLEET = 24
BASE_K = 8   # the baseline's own measured optimum


def run(policy, scenario, seed):
    eng = SimEngine(scenario, seed=seed, policy=policy, label="prio")
    eng.run(TICKS)
    k = eng.kpis()
    return k["tasks_complete"], len(eng.violations), eng.replans


def totals(factory, scenario):
    done, colls, replans = 0, [], 0
    for seed in SEEDS:
        d, c, r = run(factory(seed), scenario, seed)
        done += d
        colls.append(c)
        replans += r
    return done, colls, replans


def main() -> None:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)
    print(f"scenario=rush_50 fleet={FLEET} ticks={TICKS} seeds={SEEDS}")

    tuned = type("TunedStopAndWait", (StopAndWaitPolicy,), {"STUCK_TICKS": BASE_K})
    base, bc, _ = totals(lambda s: tuned(), scenario)
    print(f"baseline (STUCK_TICKS={BASE_K}, its optimum): {base}  coll={bc}\n")

    print(f"{'order':>12} {'total':>6} {'vs base':>9} {'coll':>10} {'replans':>9}")
    original = sp.PRIORITY_ORDER
    try:
        for flag, label in ((False, "id_order"), (True, "priority")):
            sp.PRIORITY_ORDER = flag
            done, colls, replans = totals(
                lambda s: sp.SwarmPolicy(rng=random.Random(s)), scenario
            )
            pct = 100.0 * (done - base) / base if base else 0.0
            cs = "/".join(str(c) for c in colls)
            print(f"{label:>12} {done:>6} {pct:>+8.1f}% {cs:>10} {replans:>9}")
    finally:
        sp.PRIORITY_ORDER = original


if __name__ == "__main__":
    main()
