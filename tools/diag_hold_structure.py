"""Why are robots held? Classify every hold by its ACTUAL cause.

Four earlier fixes failed because they assumed the cause was the monitor's
pairwise floor. This probe does not assume: it counts verdict kinds, measures
how far each held robot has to go, and looks for yield cycles.
"""
from __future__ import annotations

import collections
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def probe(arm: str, seed: int, ticks: int, fleet: int):
    import dataclasses
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    eng = SimEngine(scen, seed=seed, policy=_make_policy(arm, seed), label=arm)

    kinds = collections.Counter()
    held_hist = collections.Counter()
    moved_any = collections.Counter()
    for _ in range(ticks):
        eng.step()
        v = eng._last_verdicts or {}
        held = 0
        for rid, verdict in v.items():
            kinds[verdict.kind.value] += 1
            if (verdict.speed_scale or 0.0) < 0.05:
                held += 1
        held_hist[held] += 1
        for rid, r in eng.robots.items():
            if r.velocity > 0.01:
                moved_any[rid] += 1

    k = eng.kpis()
    print(f"--- {arm} seed={seed} fleet={fleet} ticks={ticks} ---")
    print(f"done={k['tasks_complete']} coll={k['collisions']} replans={k['replans']}")
    print(f"verdict kinds: {dict(kinds)}")
    avg_held = sum(n * c for n, c in held_hist.items()) / max(1, sum(held_hist.values()))
    print(f"avg robots held per tick: {avg_held:.1f} of {fleet}")
    never = [r for r in eng.robots if moved_any[r] == 0]
    barely = [r for r in eng.robots if 0 < moved_any[r] < ticks * 0.05]
    print(f"robots that NEVER moved: {len(never)}  moved <5% of ticks: {len(barely)}")
    mv = sorted(moved_any.values())
    print(f"move-tick distribution: min={mv[0]} p25={mv[len(mv)//4]} "
          f"med={mv[len(mv)//2]} p75={mv[3*len(mv)//4]} max={mv[-1]}")
    st = eng.policy.stats() if hasattr(eng.policy, "stats") else {}
    for key in ("monitor_vetoes", "reroutes", "yields", "contests", "contests_won"):
        if key in st:
            print(f"  policy.{key} = {st[key]}")
    print()


if __name__ == "__main__":
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    for arm in ("baseline", "swarmos"):
        probe(arm, 11, ticks, fleet)
