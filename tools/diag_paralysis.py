#!/usr/bin/env python3
"""Measure WHY the full arbiter is slower than the baseline, now that the
collision metric is trustworthy.

State of play after the collision-event fix (rush_50, fleet 24, 900 ticks):

  config         done   collisions
  baseline         19      0
  monitor_only     13      1
  ladder_only      37     54..72   (was reported as 2152, a 40x overcount)
  full             13      0

So safety is solved - full is collision-free on every seed - and the entire
remaining gap is throughput. full completes 13 where the baseline completes 19,
and the ladder alone would complete 37 if it were safe.

The hypothesis this script tests is that the kernel is not merely cautious but
PARALYSED, and specifically that it is holding robots that the baseline would
have let move. The evidence so far is circumstantial: 10850 WAIT verdicts,
11201 monitor vetoes, 12.4 vetoes per tick, 17 of 24 robots held simultaneously.

What is printed, per configuration:

  verdict mix        how often each rung fires. A healthy graded kernel should
                     show many SLOW and few WAIT. If WAIT dominates, the
                     graded fallback is not being used and the kernel has
                     collapsed back to a binary veto.
  clamp ratio        monitor_overrides / (overrides + vetoes). This is the
                     single most diagnostic number: it is the fraction of
                     interventions that reduced speed rather than stopping the
                     robot outright. Near 0 means the four MONITOR_SCALES are
                     all failing and only a full stop ever clears the floor.
  held robots        robots_vetoed_now, robots under an active veto streak.
  reroutes           how often MONITOR_STUCK_TICKS had to break a wedge. The
                     baseline's equivalent is its own STUCK_TICKS recovery.
  overlap_ticks      pair-ticks spent inside the collision threshold. New
                     metric from the collision-event fix. A large value with
                     zero collisions means one long frozen overlap.
  moving fraction    the share of robot-ticks spent with speed_scale > 0.
                     This is the cleanest measure of paralysis and is directly
                     comparable across configurations.
"""

from __future__ import annotations

import dataclasses
import random

from app.sim.engine import SimEngine
from app.sim.scenarios import get_scenario
from app.sim.policy import StopAndWaitPolicy, Verdict, VerdictKind
from app.coordination.swarm_policy import SwarmPolicy

TICKS = 900
SEEDS = (11, 13, 17)
FLEET = 24


class MonitorOnlyPolicy(SwarmPolicy):
    """Safety kernel only - the negotiation ladder always proposes PROCEED."""

    name = "monitor_only"

    def _decide(self, rid, me, inbox):  # type: ignore[override]
        return Verdict(robot_id=rid, kind=VerdictKind.PROCEED, reason="ladder disabled")


CONFIGS = {
    "baseline": lambda s: StopAndWaitPolicy(),
    "monitor_only": lambda s: MonitorOnlyPolicy(rng=random.Random(s)),
    "ladder_only": lambda s: SwarmPolicy(rng=random.Random(s), monitor=False),
    "full": lambda s: SwarmPolicy(rng=random.Random(s)),
}


def main() -> int:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)

    for name, make in CONFIGS.items():
        print(f"\n=== {name} ===")
        for seed in SEEDS:
            policy = make(seed)
            eng = SimEngine(scenario, seed=seed, policy=policy, label="paralysis")

            moving = 0
            total = 0
            for _ in range(TICKS):
                eng.step()
                for r in eng.robots.values():
                    if r.failed:
                        continue
                    total += 1
                    if r.speed_scale > 0.0:
                        moving += 1

            k = eng.kpis()
            st = policy.stats() if hasattr(policy, "stats") else {}
            vetoes = st.get("monitor_vetoes", 0)
            overrides = st.get("monitor_overrides", 0)
            denom = vetoes + overrides
            clamp = (overrides / denom) if denom else float("nan")

            print(
                f"  seed {seed}: done={k['tasks_complete']:3d} "
                f"coll={k['collisions']:3d} "
                f"overlap_ticks={k.get('overlap_ticks', 0):5d} "
                f"moving={100.0 * moving / max(1, total):5.1f}%"
            )
            print(
                f"           verdicts={eng.verdict_counts} "
                f"replans={eng.replans}"
            )
            if denom:
                print(
                    f"           vetoes={vetoes} clamps={overrides} "
                    f"clamp_ratio={clamp:.3f} held_now={st.get('robots_vetoed_now')} "
                    f"policy_reroutes={st.get('reroutes')}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
