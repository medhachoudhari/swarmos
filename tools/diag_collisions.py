#!/usr/bin/env python3
"""Dump the first collisions in monitor_only, with the verdicts that allowed them.

Why this exists. Removing the non-closing exemption made the safety kernel
STRICTLY more conservative - the only change was that one `continue` which
skipped a veto is gone, so every motion the kernel used to permit it still
permits, and some it used to permit it now blocks. A strictly more conservative
kernel cannot introduce collisions by permitting motion. Yet monitor_only went
from 0 and 1 collisions to 470 and 398.

Therefore the collisions are not being permitted by the floor test at all. They
arrive through some path that bypasses it. The candidates, in order of
likelihood:

  1. REROUTE. It carries speed_scale 0.0, so the robot does not move on that
     tick, but it also calls robot.clear_path() in the engine and replans with
     an avoid-hint. A stricter kernel produces far more REROUTEs, so if the
     replan itself can place a robot on top of a peer, this is the path.
  2. The granted map. Peers later in sort order are modelled as stationary
     POINTS when this robot is arbitrated. If a robot is held it publishes a
     point, and a peer arbitrated earlier that assumed it would move may have
     been cleared against the wrong segment.
  3. A robot with no path being treated as absent from sensing.

This prints, for each of the first violations, the tick, the pair, their
verdict kinds and speed scales on the tick before, and whether either had just
been rerouted. That distinguishes 1 from 2 immediately: if both robots show
speed_scale 0.0 on the tick of the collision, nobody moved into anybody and the
overlap was created by a teleport or a replan, not by a permitted step.
"""

from __future__ import annotations

import dataclasses
import random

from app.sim.engine import SimEngine
from app.sim.scenarios import get_scenario
from app.coordination.swarm_policy import SwarmPolicy
from app.sim.policy import Verdict, VerdictKind

TICKS = 900
SEED = 13
FLEET = 24
MAX_SHOW = 12


class MonitorOnlyPolicy(SwarmPolicy):
    """Safety kernel with the negotiation ladder removed.

    Identical to the configuration in diag_isolate.py, so the numbers here are
    directly comparable with that harness.
    """

    name = "monitor_only"

    def _decide(self, rid, me, inbox):  # type: ignore[override]
        return Verdict(robot_id=rid, kind=VerdictKind.PROCEED, reason="ladder disabled")


def main() -> int:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)
    policy = MonitorOnlyPolicy(rng=random.Random(SEED))
    eng = SimEngine(scenario, seed=SEED, policy=policy, label="diag")

    shown = 0
    for tick in range(TICKS):
        before = len(eng.violations)
        eng.step() if hasattr(eng, "step") else eng.run(1)
        if len(eng.violations) > before and shown < MAX_SHOW:
            for v in eng.violations[before:]:
                if shown >= MAX_SHOW:
                    break
                ids = list(getattr(v, "robot_ids", ()) or ())
                print(f"\ntick {tick} violation kind={getattr(v, 'kind', '?')} "
                      f"ids={ids} sep={getattr(v, 'separation_m', None)}")
                for rid in ids:
                    vd = eng._last_verdicts.get(rid)
                    rb = eng.robots.get(rid)
                    print(f"   {rid}: verdict="
                          f"{vd.kind.value if vd else 'NONE'} "
                          f"scale={vd.speed_scale if vd else 'NONE'} "
                          f"reason={vd.reason[:70] if vd else ''}")
                    if rb is not None:
                        print(f"        pos=({rb.position.x:.2f},{rb.position.y:.2f}) "
                              f"pathlen={len(rb.path) if rb.path else 0} "
                              f"speed_scale={rb.speed_scale:.2f}")
                shown += 1

    k = eng.kpis()
    print(f"\ntotals: done={k['tasks_complete']} collisions={k['collisions']} "
          f"near={k['near_misses']} replans={k.get('replans')}")
    print(f"verdict counts: {eng.verdict_counts}")
    print(f"policy stats: {policy.stats()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
