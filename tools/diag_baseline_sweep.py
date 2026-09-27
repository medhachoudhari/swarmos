"""Sweep StopAndWaitPolicy.STUCK_TICKS to find the BASELINE's own optimum.

This exists to keep the headline claim honest. MONITOR_STUCK_TICKS was tuned from
30 to 4 because measurement showed a clear interior peak there, but the original
reason it was pinned at 30 was that StopAndWaitPolicy.STUCK_TICKS is also 30: if
only SWARMOS gets a faster deadlock escape hatch, then any improvement might be
recovery latency rather than negotiation, and we would be winning the benchmark by
changing the benchmark.

There are two defensible ways to settle it, and this script produces the data for
both:

  1. LIKE-FOR-LIKE. Compare SWARMOS at k against the baseline at the same k. Fair
     by construction, but assumes the same k is the right operating point for two
     mechanisms that are not actually the same mechanism.
  2. BEST-VERSUS-BEST. Tune each policy independently and compare each at its own
     optimum. This is the comparison an honest paper makes, because a reviewer
     will always ask whether the baseline was handicapped.

The number quoted to judges must be the WEAKER of the two. STUCK_TICKS is a class
attribute, so the baseline is swept by subclassing rather than by editing
app/sim/policy.py, which is the frozen reference implementation.
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
VALUES = (2, 3, 4, 5, 6, 8, 12, 20, 30)


def run(policy, scenario, seed):
    eng = SimEngine(scenario, seed=seed, policy=policy, label="bsweep")
    eng.run(TICKS)
    return eng.kpis()["tasks_complete"], len(eng.violations), eng.replans


def totals(factory, scenario):
    done = 0
    colls = []
    replans = 0
    for seed in SEEDS:
        d, c, r = run(factory(seed), scenario, seed)
        done += d
        colls.append(c)
        replans += r
    return done, colls, replans


def main() -> None:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)
    print(f"scenario=rush_50 fleet={FLEET} ticks={TICKS} seeds={SEEDS}")
    print(f"swarmos committed MONITOR_STUCK_TICKS={sp.MONITOR_STUCK_TICKS}\n")

    # --- baseline swept over its own deadlock threshold ---
    print("BASELINE StopAndWaitPolicy.STUCK_TICKS sweep")
    print(f"{'stuck':>6} {'total':>6} {'coll':>12} {'replans':>9}")
    base_rows = {}
    for value in VALUES:
        cls = type("TunedStopAndWait", (StopAndWaitPolicy,), {"STUCK_TICKS": value})
        done, colls, replans = totals(lambda s, c=cls: c(), scenario)
        base_rows[value] = (done, colls, replans)
        cs = "/".join(str(c) for c in colls)
        print(f"{value:>6} {done:>6} {cs:>12} {replans:>9}")

    # --- swarmos swept over the same range, for the like-for-like diagonal ---
    print("\nSWARMOS MONITOR_STUCK_TICKS sweep")
    print(f"{'stuck':>6} {'total':>6} {'coll':>12} {'replans':>9}")
    swarm_rows = {}
    original = sp.MONITOR_STUCK_TICKS
    try:
        for value in VALUES:
            sp.MONITOR_STUCK_TICKS = value
            done, colls, replans = totals(
                lambda s: sp.SwarmPolicy(rng=random.Random(s)), scenario
            )
            swarm_rows[value] = (done, colls, replans)
            cs = "/".join(str(c) for c in colls)
            print(f"{value:>6} {done:>6} {cs:>12} {replans:>9}")
    finally:
        sp.MONITOR_STUCK_TICKS = original

    # --- verdicts ---
    print("\nLIKE-FOR-LIKE (same k on both sides)")
    print(f"{'k':>6} {'base':>6} {'swarm':>6} {'delta':>9}")
    for value in VALUES:
        b = base_rows[value][0]
        s = swarm_rows[value][0]
        pct = 100.0 * (s - b) / b if b else 0.0
        print(f"{value:>6} {b:>6} {s:>6} {pct:>+8.1f}%")

    # Only collision-free configurations are admissible: a throughput win bought
    # with a collision is not a win, it is a safety failure.
    def best(rows):
        safe = {k: v for k, v in rows.items() if sum(v[1]) == 0}
        if not safe:
            return None, None
        k = max(safe, key=lambda k: safe[k][0])
        return k, safe[k][0]

    bk, bv = best(base_rows)
    sk, sv = best(swarm_rows)
    print("\nBEST-VERSUS-BEST (collision-free configurations only)")
    print(f"  baseline optimum  k={bk}  total={bv}")
    print(f"  swarmos  optimum  k={sk}  total={sv}")
    if bv:
        print(f"  honest headline delta: {100.0 * (sv - bv) / bv:+.1f}%")


if __name__ == "__main__":
    main()
