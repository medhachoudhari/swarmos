"""Attribute every monitor veto to a cause, before attempting another fix.

Three ladder-side experiments have now been measured and rejected, and all three
pointed the same way: the remaining deficit is the KERNEL's pessimism, not the
negotiation. Before writing a fourth patch, this instrument establishes WHICH
pessimism, because there are three candidates and they call for different fixes.

For every veto (all MONITOR_SCALES exhausted, robot held at speed 0) the blocking
peer is classified as:

  already_inside  the pair was ALREADY closer than HARD_STOP_M before this robot
                  moved at all. No step can fix this - see the arithmetic in
                  section 2 of SESSION_SUMMARY_20260921_0050 - so these vetoes
                  are pure dead time until MONITOR_STUCK_TICKS fires 30 ticks
                  later. If this dominates, the fix is recovery latency.

  undecided_peer  the peer had NOT yet been decided this tick, so `granted`
                  had no entry and the monitor modelled it as a stationary
                  POINT at its current position. Because arbitrate resolves in
                  ascending id order, every robot is judged against all
                  HIGHER-id peers as if parked. If this dominates, the fix is a
                  better model for not-yet-decided peers.

  held_peer       the peer was decided and genuinely granted no motion. This
                  veto is correct and unavoidable: something really is in the
                  way.

  moving_peer     the peer was granted real motion and the two swept paths
                  conflict. Also correct - this is the kernel doing its job.

Counting these tells us which of the three is worth attacking. Read-only: it
subclasses SwarmPolicy and re-derives the classification from the same inputs
without altering any decision, so the run is byte-identical to a normal one.
"""

import collections
import dataclasses
import math
import random
import sys

sys.path.insert(0, ".")

from app.coordination.swarm_policy import (          # noqa: E402
    HARD_STOP_M, INTERACT_RADIUS_M, MAX_STEP_M, SwarmPolicy,
)
from app.sim.engine import SimEngine                 # noqa: E402
from app.sim.scenarios import get_scenario           # noqa: E402

TICKS = 900
SEEDS = (11, 13, 17)
FLEET = 24


class AuditedPolicy(SwarmPolicy):
    """SwarmPolicy that records why each veto happened. Decisions unchanged."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.causes = collections.Counter()
        self.veto_events = 0

    def _monitor(self, rid, me, proposal, inbox, granted):
        final = super()._monitor(rid, me, proposal, inbox, granted)

        wanted = (proposal.speed_scale or 0.0) > 0.0
        got = (final.speed_scale or 0.0) > 0.0
        if not wanted or got:
            return final                     # not a veto, nothing to attribute

        self.veto_events += 1

        # Re-derive the nearest relevant peer exactly as the monitor sees it.
        here = (me.position.x, me.position.y)
        worst = None
        for peer_id in sorted(inbox):
            if peer_id == rid:
                continue
            peer = inbox[peer_id].state
            there = (peer.position.x, peer.position.y)
            now = math.dist(here, there)
            if now > INTERACT_RADIUS_M + MAX_STEP_M:
                continue
            if worst is None or now < worst[1]:
                worst = (peer_id, now)

        if worst is None:
            self.causes["no_peer_in_range"] += 1
            return final

        peer_id, now = worst
        if now < HARD_STOP_M:
            # Unsatisfiable by construction: already inside the floor.
            self.causes["already_inside"] += 1
        elif peer_id not in granted:
            # Modelled as a parked point purely because of id resolution order.
            self.causes["undecided_peer"] += 1
        else:
            seg = granted[peer_id]
            moved = math.dist(seg[0], seg[1])
            self.causes["moving_peer" if moved > 1e-9 else "held_peer"] += 1
        return final


def main() -> None:
    scenario = dataclasses.replace(get_scenario("rush_50"), fleet_size=FLEET)
    grand = collections.Counter()
    grand_vetoes = 0

    print(f"scenario=rush_50 fleet={FLEET} ticks={TICKS}\n")
    for seed in SEEDS:
        policy = AuditedPolicy(rng=random.Random(seed))
        eng = SimEngine(scenario, seed=seed, policy=policy, label="veto_audit")
        eng.run(TICKS)
        k = eng.kpis()

        total = policy.veto_events or 1
        print(f"seed {seed}: done={k['tasks_complete']:3d} "
              f"coll={len(eng.violations):3d} vetoes={policy.veto_events}")
        for cause, n in policy.causes.most_common():
            print(f"           {cause:16s} {n:7d}  {100.0*n/total:5.1f}%")
        grand += policy.causes
        grand_vetoes += policy.veto_events

    print("\nall seeds")
    total = grand_vetoes or 1
    for cause, n in grand.most_common():
        print(f"  {cause:16s} {n:8d}  {100.0*n/total:5.1f}%")
    print(f"  {'TOTAL':16s} {grand_vetoes:8d}")


if __name__ == "__main__":
    main()
