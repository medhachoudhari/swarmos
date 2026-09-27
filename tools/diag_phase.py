"""Where does the task lifecycle actually stall?

Neither arm completes a task in 400 ticks, so the 6-vs-22 gap at 900 ticks is
a tail effect. This probe tracks the phase histogram and the first-completion
tick, which tells us whether SWARMOS is slower per task or stuck earlier in
the pipeline.
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

    first_pick = None
    first_done = None
    picks = 0
    marks = {}
    for t in range(ticks):
        snap = eng.step()
        for ev in snap.events if hasattr(snap, "events") else []:
            pass
        for ev in (snap.as_dict().get("events") or []):
            if ev.get("type") == "task_picked":
                picks += 1
                if first_pick is None:
                    first_pick = t
            if ev.get("type") == "task_complete" and first_done is None:
                first_done = t
        if t in (200, 400, 600, 900, 1200, 1800):
            ph = collections.Counter(eng._phase.get(r) for r in eng.robots)
            marks[t] = (eng.kpis()["tasks_complete"], picks, dict(ph))

    k = eng.kpis()
    print(f"--- {arm} seed={seed} fleet={fleet} ticks={ticks} ---")
    print(f"first task_picked tick = {first_pick}")
    print(f"first task_complete tick = {first_done}")
    print(f"total picks = {picks}   completions = {k['tasks_complete']}")
    for t, (done, pk, ph) in marks.items():
        print(f"  t={t:5d} done={done:3d} picks={pk:4d} phases={ph}")
    print()


if __name__ == "__main__":
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    for arm in ("baseline", "swarmos"):
        probe(arm, 11, ticks, fleet)
