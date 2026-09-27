"""Isolation harness: which LAYER of the arbiter is costing throughput?

Seven tuning attempts on SwarmPolicy all lost to StopAndWaitPolicy, with the
monitor vetoing roughly a third of all robot-ticks no matter how the thresholds
were moved. Tuning further without localising the fault is guessing, so this
script removes one layer at a time and measures what is left.

The four configurations, and what each one PROVES:

  baseline        StopAndWaitPolicy. The number to beat.

  monitor_only    SwarmPolicy with the ladder stubbed out - every robot always
                  proposes PROCEED, so the safety monitor is the only thing
                  making decisions. This is the key measurement. The monitor now
                  uses the same 0.75 m floor, the same segment geometry and the
                  same ascending-id `granted` resolution as the baseline, so it
                  is ALGORITHMICALLY EQUIVALENT to the baseline and must score
                  about the same. If it does, the loss is in the ladder. If it
                  does NOT, the loss is below the ladder - in the radio, the
                  inbox, or the view staleness - and no amount of threshold
                  tuning will ever fix it.

  ladder_only     SwarmPolicy with the monitor disabled. Isolates how much of
                  the waiting the negotiation is responsible for on its own.
                  Collisions here are expected and are not a defect: this
                  configuration exists precisely to show what the monitor is
                  buying.

  full            SwarmPolicy as shipped.

Run:
  cd <repo> && PYTHONPATH=. python3 tools/diag_isolate.py
"""

from __future__ import annotations

import dataclasses
import random

from app.coordination.swarm_policy import SwarmPolicy
from app.sim.engine import SimEngine
from app.sim.policy import StopAndWaitPolicy, Verdict, VerdictKind

# The baseline's own collision-free optimum, measured by diag_baseline_sweep.py
# (29 completions at k=8 versus 19 at the k=30 default). STUCK_TICKS is a class
# attribute precisely so it can be retuned without editing app/sim/policy.py.
BASE_STUCK_TICKS = 8
TunedStopAndWait = type(
    "TunedStopAndWait", (StopAndWaitPolicy,), {"STUCK_TICKS": BASE_STUCK_TICKS}
)
from app.sim.scenarios import get_scenario

TICKS = 900
SEEDS = (11, 13, 17)
FLEET = 24


class MonitorOnlyPolicy(SwarmPolicy):
    """SwarmPolicy with the negotiation removed.

    Every robot proposes PROCEED, so the only thing that can stop a robot is the
    X-09 safety monitor. Since that monitor enforces the baseline's own rule with
    the baseline's own geometry and resolution order, this configuration should
    land within noise of the baseline. Any large gap is evidence that the defect
    lives below the ladder rather than in it.
    """

    name = "monitor_only"

    def _decide(self, rid, me, inbox) -> Verdict:
        return Verdict(
            robot_id=rid, kind=VerdictKind.PROCEED, reason="ladder disabled",
        )


def run(policy_factory, seed: int) -> dict:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)
    eng = SimEngine(scenario, seed=seed, policy=policy_factory(seed), label="diag")
    eng.run(TICKS)
    k = eng.kpis()
    return {
        "done": k.get("tasks_complete", 0),
        "coll": k.get("collisions", 0),
        "near": k.get("near_misses", 0),
        "p95": (k.get("compute") or {}).get("p95_ms", 0.0),
    }


def main() -> None:
    configs = {
        "baseline": lambda s: TunedStopAndWait(),
        "monitor_only": lambda s: MonitorOnlyPolicy(rng=random.Random(s)),
        "ladder_only": lambda s: SwarmPolicy(rng=random.Random(s), monitor=False),
        "full": lambda s: SwarmPolicy(rng=random.Random(s)),
    }

    print(f"scenario=rush_50 fleet={FLEET} ticks={TICKS}\n")
    totals: dict[str, int] = {name: 0 for name in configs}

    for seed in SEEDS:
        print(f"seed {seed}")
        for name, factory in configs.items():
            k = run(factory, seed)
            totals[name] += k["done"]
            print(
                f"  {name:13s} done={k['done']:4d} "
                f"coll={k['coll']:4d} "
                f"near={k['near']:6d} "
                f"p95={k['p95']:.1f}ms"
            )
        print()

    print("total completions over all seeds")
    base = max(1, totals["baseline"])
    for name, total in totals.items():
        delta = (total - totals["baseline"]) / base * 100.0
        print(f"  {name:13s} {total:4d}   vs baseline {delta:+.1f}%")


if __name__ == "__main__":
    main()

# File contains AI-generated response based on internal company sources
