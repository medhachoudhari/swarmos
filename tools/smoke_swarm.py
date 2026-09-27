"""Quick head-to-head smoke check for the SWARMOS arbiter.

Not a test and not evidence - the real evidence run is app/db/benchmark.py over
>=10 seeds with a paired CI. This exists only to give a fast signal while the
policy is being tuned: does it finish more tasks than stop-and-wait, and does it
stay collision free.

Run:
  PYTHONPATH=. python3 tools/smoke_swarm.py
"""

from __future__ import annotations

import dataclasses
import random

from app.coordination.swarm_policy import SwarmPolicy
from app.sim.engine import SimEngine
from app.sim.policy import NoOpPolicy, StopAndWaitPolicy
from app.sim.scenarios import get_scenario

TICKS = 900          # 90 s of warehouse time
SEEDS = (11, 13, 17)


def run(scenario, seed: int, policy):
    eng = SimEngine(scenario, seed=seed, policy=policy, label="smoke")
    eng.run(TICKS)
    k = eng.kpis()
    return {
        "completed": k.get("tasks_complete", 0),
        "per_min": k.get("tasks_per_min", 0.0),
        "avg_s": k.get("avg_completion_s"),
        "collisions": k.get("collisions", 0),
        "near_misses": k.get("near_misses", 0),
        "p95_ms": (k.get("compute") or {}).get("p95_ms", 0.0),
        "policy": policy.stats(),
    }



def main() -> None:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=24)
    print(f"scenario={scenario.name} fleet={scenario.fleet_size} ticks={TICKS}")

    for seed in SEEDS:
        base = run(scenario, seed, StopAndWaitPolicy())
        swarm = run(scenario, seed, SwarmPolicy(rng=random.Random(seed)))
        delta = (
            100.0 * (swarm["completed"] - base["completed"]) / base["completed"]
            if base["completed"]
            else float("inf")
        )
        print(f"\nseed {seed}")
        print(
            f"  baseline : done={base['completed']:4d} coll={base['collisions']:3d} "
            f"near={base['near_misses']:4d} p95={base['p95_ms']:.1f}ms"
        )
        print(
            f"  swarmos  : done={swarm['completed']:4d} coll={swarm['collisions']:3d} "
            f"near={swarm['near_misses']:4d} p95={swarm['p95_ms']:.1f}ms  "
            f"throughput {delta:+.1f}%"
        )
        s = swarm["policy"]
        print(
            f"    verdicts={s['verdicts']} contests={s['contests']} "
            f"vetoes={s['monitor_vetoes']} reroutes={s['reroutes']} "
            f"msgs/robot/tick={s['msgs_per_robot_tick']}"
        )

    # Control condition: without any arbitration the fleet must collide, which
    # is how the collision counter is shown to be a measurement.
    ctrl = run(scenario, SEEDS[0], NoOpPolicy())
    print(f"\ncontrol (no arbitration): collisions={ctrl['collisions']}")


if __name__ == "__main__":
    main()

# File contains AI-generated response based on internal company sources
