"""Verification of the two published SIH26123 success criteria.

  C1  zero collisions
  C2  at least 20 pct reduction in task completion time versus a
      stop-and-wait baseline

Both are measured here, paired: the same seed, the same scenario and the same
fleet drive both arms, so the only difference is the coordination policy. Every
scenario in SCENARIOS is run, not a chosen favourite, and the report prints the
per-scenario verdict as well as the aggregate. A criterion that passes on one
scenario and fails on another is reported as exactly that.

C2 is measured on avg_completion_s, which is mean time from task assignment to
task completion - the quantity the criterion actually names. tasks_per_min is
reported alongside it for context but is NOT the criterion; throughput and
latency are different claims and conflating them would be dishonest.

Runs are 1800 ticks (180 s sim time) because 900 ticks is still inside the
startup transient and would flatter whichever arm happens to dispatch first.

Usage: PYTHONPATH=. python3 tools/verify_criteria.py [ticks]
"""
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SEEDS = (11, 13, 17)
TICKS = 1800
C2_TARGET_PCT = 20.0


def run(policy_name, scen, seed, ticks):
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


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else TICKS
    print(f"SIH26123 success-criteria verification")
    print(f"ticks={ticks} ({ticks / 10.0:.0f} s sim time)  seeds={SEEDS}")
    print(f"C1 zero collisions   C2 >= {C2_TARGET_PCT:.0f} pct completion-time reduction\n")

    all_coll = 0
    c2_rows = []

    for name in sorted(SCENARIOS):
        scen = SCENARIOS[name]
        print(f"--- {name}  (fleet {scen.fleet_size}) "
              f"{'-' * max(0, 40 - len(name))}")
        print(f"{'seed':>5} {'arm':>9} {'coll':>5} {'near':>5} {'done':>5} "
              f"{'avg_compl_s':>12} {'tasks/min':>10} {'p95_ms':>7}")
        for seed in SEEDS:
            pair = {}
            for arm in ("baseline", "swarmos"):
                r = run(arm, scen, seed, ticks)
                pair[arm] = r
                all_coll += r["collisions"]
                ac = "--" if r["avg_completion_s"] is None else f"{r['avg_completion_s']:.2f}"
                print(f"{seed:>5} {arm:>9} {r['collisions']:>5} "
                      f"{r['near_misses']:>5} {r['done']:>5} {ac:>12} "
                      f"{r['tasks_per_min']:>10.2f} {r['p95_ms']:>7.2f}")
            b = pair["baseline"]["avg_completion_s"]
            s = pair["swarmos"]["avg_completion_s"]
            if b and s:
                c2_rows.append((name, seed, b, s, (b - s) / b * 100.0))
        print()

    print("=" * 72)
    print(f"C1 zero collisions: total collisions across every arm, seed and "
          f"scenario = {all_coll}")
    print("    " + ("PASS" if all_coll == 0 else f"FAIL ({all_coll} collisions)"))

    print(f"\nC2 completion-time reduction (baseline -> swarmos, "
          f"avg_completion_s):")
    if not c2_rows:
        print("    NOT MEASURABLE - no seed completed tasks in both arms.")
        print("    Reporting this rather than substituting throughput.")
        return 0
    print(f"{'scenario':>24} {'seed':>5} {'baseline':>9} {'swarmos':>9} {'reduction':>10}")
    for name, seed, b, s, red in c2_rows:
        print(f"{name:>24} {seed:>5} {b:>9.2f} {s:>9.2f} {red:>9.1f}%")
    mean_red = sum(r[4] for r in c2_rows) / len(c2_rows)
    print(f"\n    mean reduction over {len(c2_rows)} paired runs: {mean_red:+.1f} pct")
    print("    " + ("PASS" if mean_red >= C2_TARGET_PCT
                    else f"DOES NOT MEET the {C2_TARGET_PCT:.0f} pct bar"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
