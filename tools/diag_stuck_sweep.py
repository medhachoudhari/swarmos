"""Sweep MONITOR_STUCK_TICKS, the monitor's only un-wedging mechanism.

tools/diag_veto_cause.py attributed all 13299 vetoes across three seeds:

    held_peer        59.4%   blocked by a peer that was itself granted no motion
    already_inside   40.2%   pair already inside HARD_STOP_M, unsatisfiable
    moving_peer       0.5%   genuine conflict with a peer that is moving
    undecided_peer    0.0%

So 99.5% of vetoes are caused by robots that are ALREADY STOPPED, and the kernel
almost never blocks real moving traffic. That reframes the deficit completely: it
is not a geometry problem, it is a STALL CASCADE. A is held, B is held because A
is in the way, C is held because B is in the way, and the chain sustains itself
because a held robot keeps occupying the space that holds the next one.

The 40.2% `already_inside` share is unsatisfiable by construction - no fraction of
a step can clear a floor the pair is already inside - so those robots wait out the
full MONITOR_STUCK_TICKS before the monitor reroutes them. At 10 Hz, 30 ticks is
3 SECONDS of dead time per wedge, and every robot stalled behind them inherits it.

MONITOR_STUCK_TICKS is therefore the lever, so measure it rather than guess. Too
low risks thrashing (a reroute every few ticks, which is how the rejected
no-yield-to-stationary patch lost); too high is the dead time above.
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
VALUES = (1, 2, 3, 4, 5)


def run(policy_factory, scenario, seed):
    policy = policy_factory(seed)
    eng = SimEngine(scenario, seed=seed, policy=policy, label="sweep")
    eng.run(TICKS)
    return eng.kpis()["tasks_complete"], len(eng.violations), eng.replans


def main() -> None:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)

    base = sum(run(lambda s: StopAndWaitPolicy(), scenario, s)[0] for s in SEEDS)
    print(f"scenario=rush_50 fleet={FLEET} ticks={TICKS} seeds={SEEDS}")
    print(f"baseline total={base}\n")
    print(f"{'stuck':>6} {'total':>6} {'vs base':>9} {'coll':>12} {'replans':>9}")

    original = sp.MONITOR_STUCK_TICKS
    try:
        for value in VALUES:
            sp.MONITOR_STUCK_TICKS = value
            done = []
            colls = []
            replans = 0
            for seed in SEEDS:
                d, c, r = run(
                    lambda s: sp.SwarmPolicy(rng=random.Random(s)), scenario, seed
                )
                done.append(d)
                colls.append(c)
                replans += r
            total = sum(done)
            pct = 100.0 * (total - base) / base if base else 0.0
            cs = "/".join(str(c) for c in colls)
            print(f"{value:>6} {total:>6} {pct:>+8.1f}% {cs:>12} {replans:>9}")
    finally:
        sp.MONITOR_STUCK_TICKS = original


if __name__ == "__main__":
    main()
