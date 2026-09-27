"""Does honest sensor drift get an innocent robot quarantined?

This is the question that decides whether the containment mechanism is usable.
An honest robot's odometry drift accumulates without bound, so given enough
distance travelled it MUST eventually exceed a fixed 1.5 m claim tolerance - at
which point the fleet contains a robot whose only crime is having wheels.
"""
from app.coordination.swarm_policy import SwarmPolicy
from app.sim.engine import SimEngine
from app.sim.scenarios import get_scenario
from app.sim.sensing import SENSING_REALISTIC

print("SENSING_REALISTIC:", SENSING_REALISTIC.as_dict())

spec = get_scenario("rush_50")
import dataclasses
noisy = dataclasses.replace(spec, sensing=SENSING_REALISTIC)

e = SimEngine(noisy, seed=42, policy=SwarmPolicy(integrity=True))
for horizon in (100, 300, 600, 900):
    while e.tick < horizon:
        e.step()
    s = e.policy.stats()["integrity"]
    drift = max(abs(r.drift_x) + abs(r.drift_y) for r in e.robots.values())
    print(f"tick {horizon:4d}  accusations={s['council']['accusations']:5d} "
          f"contained={len(s['council']['contained']):2d} "
          f"max|drift|={drift:.3f} m  contained={s['council']['contained']}")
