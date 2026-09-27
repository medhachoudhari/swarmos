"""Throwaway diagnostic: why does the TO_DROP / TO_CHARGER leg never finish?

Not a test. Run with:
  PYTHONPATH=. python3 tools/diag_second_leg.py
"""

from collections import Counter

from app.sim import SimEngine, StopAndWaitPolicy
from app.sim.engine import SERVICE_RADIUS_M

eng = SimEngine("rush_50", seed=11, policy=StopAndWaitPolicy())
eng.run(900)

print("events:", Counter(e["kind"] for e in eng.events))
print("tasks :", Counter(t.status.value for t in eng.tasks.values()))
print("robots:", Counter(r.status.value for r in eng.robots.values()))
print("kpis  :", {k: eng.kpis()[k] for k in
                  ("tasks_complete", "robots_charging", "replans", "collisions")})
print("policy:", eng.policy.stats())
print("drop cells:", eng.drop_cells[:4], "pick cells:", eng.pick_cells[:4])

shown = 0
for rid in sorted(eng.robots):
    r = eng.robots[rid]
    phase = eng._phase.get(rid)
    if phase != "TO_DROP" or shown >= 4:
        continue
    shown += 1
    task = eng.tasks[r.current_task_id]
    dm = eng.warehouse.cell_to_m(*task.drop)
    goal = eng._goal_cell.get(rid)
    print(f"\n{rid} pos=({r.x:.2f},{r.y:.2f}) status={r.status.value} "
          f"vel={r.velocity:.2f} scale={r.speed_scale} dwell={eng._dwell.get(rid,0)}")
    print(f"  task={task.task_id} drop_cell={task.drop} drop_m={dm} goal_cell={goal}")
    print(f"  dist_to_drop={r.distance_to(*dm):.2f}  service_radius={SERVICE_RADIUS_M}")
    print(f"  path_len={len(r.path)} path={r.path[:6]}")
    print(f"  travelled={r.distance_travelled_m:.1f} m target={r.target}")

# Is the drop cell even a legal A* goal?
from app.sim.pathfinding import find_path, nearest_navigable
for d in eng.drop_cells[:3]:
    print(f"\ndrop {d} navigable={eng.warehouse.is_navigable(*d)} "
          f"nearest={nearest_navigable(eng.warehouse, d)}")
    p = find_path(eng.warehouse, (30, 20), d)
    print(f"  path (30,20)->{d}: {'None' if p is None else f'{len(p)} cells, tail {p[-3:]}'}")

# File contains AI-generated response based on internal company sources
