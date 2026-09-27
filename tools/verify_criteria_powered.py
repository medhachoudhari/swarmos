#!/usr/bin/env python3
"""
Powered re-measurement of SIH26123 criterion C2.

docs/SUCCESS_CRITERIA_VERIFICATION.md recorded C2 as NOT MET at +2.3 pct mean
with a -47.8 to +57.9 pct spread, and named the defect: at 1800 ticks only 1 to
16 tasks complete per run, so avg_completion_s is a single-sample statistic.
It also specified the fix - longer runs, more seeds, and a confidence interval
instead of a point estimate. This script is that fix.

Differences from tools/verify_criteria.py:
  * TICKS raised from 1800 to 9000 (900 s of sim time) so tens of tasks
    complete per arm and the mean stops being one robot's luck.
  * SEEDS raised from 3 to 9.
  * Reports a 95 percent confidence interval on the paired reduction using the
    Student t critical value, plus the per-run completed-task count so the
    reader can see whether the measurement is powered at all.
  * Reports the paired differences, not two independent means. The arms share
    seed, scenario and fleet, so the pairing is real and removes scenario
    variance from the estimate.

Usage:
    PYTHONPATH=. python3 tools/verify_criteria_powered.py [ticks] [nseeds]
"""

from __future__ import annotations

import math
import statistics
import sys
import time

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SEEDS = (11, 13, 17, 19, 23, 29, 31, 37, 41)
TICKS = 9000
C2_TARGET_PCT = 20.0

# Student t, two-sided 95 pct, by degrees of freedom. Table rather than scipy,
# which is not guaranteed present in this environment.
T95 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
    14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
    20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}


def t_crit(df: int) -> float:
    """Two-sided 95 pct critical value, falling back to the normal limit."""
    if df <= 0:
        return float("nan")
    if df in T95:
        return T95[df]
    return 1.96


def run(policy_name: str, scen, seed: int, ticks: int) -> dict:
    eng = SimEngine(scen, seed=seed, policy=_make_policy(policy_name, seed),
                    label=policy_name)
    eng.run(ticks)
    k = eng.kpis()
    return {
        "collisions": k["collisions"],
        "near_misses": k["near_misses"],
        "done": k["tasks_complete"],
        "avg_completion_s": k["avg_completion_s"],
        "tasks_per_min": k["tasks_per_min"],
        "p95_ms": k["compute"]["p95_ms"],
    }


def main() -> int:
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else TICKS
    nseeds = int(sys.argv[2]) if len(sys.argv) > 2 else len(SEEDS)
    seeds = SEEDS[:nseeds]

    print("=" * 74)
    print("SIH26123 C2 - powered re-measurement")
    print("ticks=%d (%.0f s sim)  seeds=%s  scenarios=%s"
          % (ticks, ticks * 0.1, list(seeds), sorted(SCENARIOS)))
    print("=" * 74)

    base_coll = 0
    swarm_coll = 0
    coll_detail: list[str] = []
    diffs: list[float] = []
    done_counts: list[int] = []
    t0 = time.time()

    for name in sorted(SCENARIOS):
        scen = SCENARIOS[name]
        print("\n-- %s (fleet %d)" % (name, scen.fleet_size))
        print("   %-6s %10s %10s %8s %8s %10s"
              % ("seed", "base(s)", "swarm(s)", "b_done", "s_done", "reduct"))
        for seed in seeds:
            b = run("baseline", scen, seed, ticks)
            s = run("swarmos", scen, seed, ticks)
            base_coll += b["collisions"]
            swarm_coll += s["collisions"]
            if s["collisions"]:
                coll_detail.append(
                    "%s seed=%d swarmos=%d"
                    % (name, seed, s["collisions"]))
            done_counts += [b["done"], s["done"]]

            bc, sc = b["avg_completion_s"], s["avg_completion_s"]
            if bc is None or sc is None or bc <= 0:
                print("   %-6d %10s %10s %8d %8d %10s"
                      % (seed, "--", "--", b["done"], s["done"], "n/a"))
                continue
            red = (bc - sc) / bc * 100.0
            diffs.append(red)
            print("   %-6d %10.2f %10.2f %8d %8d %9.1f%%"
                  % (seed, bc, sc, b["done"], s["done"], red))

    print("\n" + "=" * 74)
    print("C1 zero collisions in the SwarmOS arm: %d  %s"
          % (swarm_coll, "PASS" if swarm_coll == 0 else "FAIL"))
    print("   baseline arm collisions (control, expected > 0): %d"
          % base_coll)
    for line in coll_detail:
        print("   SwarmOS collision run: %s" % line)

    print("-" * 74)
    if len(diffs) < 2:
        print("C2: NOT MEASURABLE - only %d usable paired runs" % len(diffs))
        return 0

    n = len(diffs)
    mean = statistics.mean(diffs)
    sd = statistics.stdev(diffs)
    sem = sd / math.sqrt(n)
    half = t_crit(n - 1) * sem
    lo, hi = mean - half, mean + half

    print("C2 paired reduction in avg_completion_s, n=%d paired runs" % n)
    print("  mean            : %+.1f pct" % mean)
    print("  std dev         : %.1f pct" % sd)
    print("  95 pct CI       : [%+.1f, %+.1f] pct" % (lo, hi))
    print("  target          : >= %.0f pct" % C2_TARGET_PCT)
    print("  tasks completed : min=%d  median=%d  max=%d  (per arm per run)"
          % (min(done_counts), int(statistics.median(done_counts)),
             max(done_counts)))

    if lo >= C2_TARGET_PCT:
        verdict = "MET - the whole interval clears the bar"
    elif hi < C2_TARGET_PCT:
        verdict = "NOT MET - the whole interval sits below the bar"
    else:
        verdict = ("INCONCLUSIVE - the interval spans the bar, so this data "
                   "cannot decide it")
    print("  verdict         : %s" % verdict)
    print("  elapsed         : %.1f s" % (time.time() - t0))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
