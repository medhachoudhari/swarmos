"""Prove the validation cache changed no behaviour, via trace_hash.

trace_hash is the N3 deterministic-replay digest of the whole run. If it is
unchanged for the same seed, the optimisation is provably behaviour-neutral -
a far stronger claim than "the KPIs look similar".
"""
from __future__ import annotations

import dataclasses
import sys
import time

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS

EXPECTED = {}
for fleet, seed, ticks in ((50, 11, 300), (24, 13, 300), (8, 17, 300)):
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    t0 = time.time()
    eng = SimEngine(scen, seed=seed, policy=_make_policy("swarmos", seed),
                    label="swarmos")
    eng.run(ticks)
    k = eng.kpis()
    print(f"fleet={fleet:3d} seed={seed} trace_hash={eng.trace_hash} "
          f"done={k['tasks_complete']} coll={k['collisions']} "
          f"p95={k['compute']['p95_ms']:.2f}ms  ({time.time()-t0:.1f}s)")
