#!/usr/bin/env python3
"""Is the WAITING pile-up a coordination bug, or is the floor simply full?

The UI showed 29 of 50 robots WAITING at 1.73 tasks/min on rush_50. Two very
different explanations produce that same screen:

  1. a livelock in the arbiter - robots hold each other forever and throughput
     collapses to zero regardless of how many robots there are; or
  2. congestion collapse - the aisle network saturates, so adding robots past
     some point buys queueing instead of throughput.

They are distinguished by the SHAPE of throughput against fleet size, so that
is what this measures. A livelock gives a curve that falls to ~0. Congestion
gives a curve that rises, peaks, then flattens or sags while collisions stay at
zero and completions keep accruing.

Run with the real policy factory, the same way tools/verify_criteria_powered.py
builds its arms. Measuring SimEngine(..., policy=None) measures nothing.
"""

from __future__ import annotations

import copy
import sys

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

SCEN = sys.argv[1] if len(sys.argv) > 1 else "rush_50"
TICKS = int(sys.argv[2]) if len(sys.argv) > 2 else 1800
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 18
FLEETS = [4, 8, 16, 24, 32, 40, 50]


def run(fleet: int) -> dict:
    # ScenarioSpec is a frozen dataclass, so it must be REBUILT, not mutated.
    # Assigning to spec.fleet_size raises, and swallowing that exception is how
    # the first version of this sweep silently measured fleet 50 seven times.
    # This is exactly how RunLoop.start applies an operator fleet override.
    base = SCENARIOS[SCEN]
    scen = base
    if fleet != base.fleet_size:
        scen = type(base)(**{**base.__dict__, "fleet_size": fleet})
    eng = SimEngine(scen, seed=SEED, policy=_make_policy("swarmos", SEED),
                    label="swarmos")

    eng.run(TICKS)
    k = eng.kpis()

    statuses: dict[str, int] = {}
    robots = getattr(eng, "robots", None)
    seq = robots.values() if isinstance(robots, dict) else (robots or [])
    for r in seq:
        name = getattr(getattr(r, "status", None), "value", str(getattr(r, "status", "?")))
        statuses[name] = statuses.get(name, 0) + 1

    return {"kpis": k, "statuses": statuses, "fleet_actual": len(list(seq)) or k.get("robots_total")}



def pick(k: dict, *names):
    for n in names:
        if n in k and k[n] is not None:
            return k[n]
    return None


def main() -> int:
    print("scenario=%s  ticks=%d  seed=%d  policy=swarmos" % (SCEN, TICKS, SEED))
    print("")
    first = run(FLEETS[0])
    print("kpis() keys: %s" % ", ".join(sorted(first["kpis"].keys())))
    print("")
    hdr = "%-6s %7s %10s %10s %8s %9s %9s  %s"
    # "actual" is printed so a fleet override that silently failed to apply is
    # visible in the table instead of producing seven identical rows.
    print(hdr % ("fleet", "actual", "tasks/min", "completed", "colls", "replans",
                 "avg_s", "end-of-run statuses"))

    print("-" * 100)

    rows = []
    for fleet in FLEETS:
        res = first if fleet == FLEETS[0] else run(fleet)
        k = res["kpis"]
        tpm = pick(k, "tasks_per_min", "throughput_tasks_per_min")
        done = pick(k, "tasks_completed", "completed", "tasks_complete")
        coll = pick(k, "collisions", "collision_count")
        repl = pick(k, "replans", "reroutes")
        avg = pick(k, "avg_completion_s", "mean_completion_s")
        st = ", ".join("%s=%d" % (n, c) for n, c in sorted(res["statuses"].items()))
        print(hdr % (fleet,
                     res.get("fleet_actual", "--"),
                     "--" if tpm is None else "%.2f" % tpm,

                     "--" if done is None else done,
                     "--" if coll is None else coll,
                     "--" if repl is None else repl,
                     "--" if avg is None else "%.1f" % avg,
                     st or "(unavailable)"))
        rows.append((fleet, tpm, done, coll))

    print("")
    valid = [(f, t) for f, t, _, _ in rows if t is not None]
    if valid:
        best_f, best_t = max(valid, key=lambda p: p[1])
        last_f, last_t = valid[-1]
        print("peak throughput   : %.2f tasks/min at fleet %d" % (best_t, best_f))
        print("throughput at %-3d : %.2f tasks/min" % (last_f, last_t))
        if best_t > 0 and last_t < best_t:
            print("loss from peak    : %.0f%%" % (100.0 * (best_t - last_t) / best_t))
        print("")
        if last_t <= 0.05 * max(best_t, 1e-9):
            print("VERDICT: throughput collapses to ~0 - consistent with a LIVELOCK.")
        elif best_f < last_f:
            print("VERDICT: throughput peaks below the largest fleet and then falls -")
            print("         consistent with CONGESTION COLLAPSE, not a livelock.")
        else:
            print("VERDICT: throughput still rising at the largest fleet - no saturation")
            print("         inside this tick budget.")
    total_coll = sum(c for _, _, _, c in rows if c is not None)
    print("collisions across every arm: %d" % total_coll)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
