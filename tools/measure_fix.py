"""Paired A/B harness for the throughput defect (STEP 1).

Runs the stop-and-wait baseline and full SWARMOS from the identical seed and
scenario, and prints completions, collisions and replans per arm. This is the
only accepted evidence for accepting or rejecting a fix.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SEEDS = (11, 13, 17)
TICKS = 900


def run(policy_name: str, seed: int, ticks: int, fleet: int, scenario: str):
    scen = SCENARIOS[scenario]
    if fleet and fleet != scen.fleet_size:
        import dataclasses
        scen = dataclasses.replace(scen, fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy(policy_name, seed),
                    label=policy_name)
    eng.run(ticks)
    k = eng.kpis()
    return {
        "done": k["tasks_complete"],
        "coll": k["collisions"],
        "near": k["near_misses"],
        "replans": k["replans"],
        "active": k["tasks_active"],
        "tpm": k["tasks_per_min"],
        "p95": k["compute"]["p95_ms"],
    }


def main():
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else TICKS
    scenario = sys.argv[3] if len(sys.argv) > 3 else "rush_50"
    print(f"scenario={scenario} fleet={fleet} ticks={ticks} seeds={SEEDS}")
    print(f"{'arm':10s} {'seed':>5s} {'done':>5s} {'coll':>5s} {'near':>5s} "
          f"{'replan':>7s} {'act':>4s} {'tpm':>6s} {'p95ms':>6s}")
    totals = {}
    for arm in ("baseline", "swarmos"):
        tot_done = tot_coll = 0
        for seed in SEEDS:
            t0 = time.time()
            r = run(arm, seed, ticks, fleet, scenario)
            tot_done += r["done"]
            tot_coll += r["coll"]
            print(f"{arm:10s} {seed:5d} {r['done']:5d} {r['coll']:5d} "
                  f"{r['near']:5d} {r['replans']:7d} {r['active']:4d} "
                  f"{r['tpm']:6.2f} {r['p95']:6.2f}   ({time.time()-t0:.0f}s)")
        totals[arm] = (tot_done, tot_coll)
        print(f"{arm:10s} TOTAL done={tot_done} coll={tot_coll}")
    b, s = totals["baseline"], totals["swarmos"]
    verdict = "PASS" if (s[0] > b[0] and s[1] == 0) else "FAIL"
    print(f"\n{verdict}: swarmos done={s[0]} coll={s[1]} vs baseline done={b[0]} coll={b[1]}")


if __name__ == "__main__":
    main()
