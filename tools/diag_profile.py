"""Where does the 72 ms p95 tick cost go?

The budget is 100 ms at 10 Hz. Baseline runs at 7 ms, SWARMOS at 72 ms p95 -
that is only 28 ms of headroom, and a live demo at fleet 50 would be one bad
tick from a visible stall. Profile the real hot path.
"""
from __future__ import annotations

import cProfile
import dataclasses
import pstats
import sys

sys.path.insert(0, ".")

from app.api.runner import _make_policy
from app.sim.engine import SimEngine
from app.sim.scenarios import SCENARIOS


def main():
    fleet = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    ticks = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    scen = dataclasses.replace(SCENARIOS["rush_50"], fleet_size=fleet)
    eng = SimEngine(scen, seed=11, policy=_make_policy("swarmos", 11),
                    label="swarmos")
    pr = cProfile.Profile()
    pr.enable()
    eng.run(ticks)
    pr.disable()
    st = pstats.Stats(pr)
    st.sort_stats("cumulative")
    print(f"=== cumulative, fleet={fleet} ticks={ticks} ===")
    st.print_stats(22)
    st.sort_stats("tottime")
    print("=== tottime ===")
    st.print_stats(15)


if __name__ == "__main__":
    main()
