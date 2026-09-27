"""End-to-end check: does a spoofing rogue actually get contained?"""
from app.coordination.swarm_policy import SwarmPolicy
from app.sim.engine import SimEngine

# --- integrity OFF must be bit-identical to the recorded baseline ------------
a = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=False))
a.run(120)
print("integrity OFF hash:", a.trace_hash)
print("  contained:", a.policy.council.contained,
      "rejected:", a.policy.stats()["integrity"]["messages_rejected"])

# --- integrity ON, no adversary: nobody may be contained --------------------
b = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=True))
b.run(120)
s = b.policy.stats()["integrity"]
print("\nintegrity ON, honest fleet:")
print("  signed:", s["auth"]["signed"], "verified:", s["auth"]["verified"],
      "rejected:", s["auth"]["rejected"])
print("  accusations:", s["council"]["accusations"],
      "contained:", s["council"]["contained"])

# --- integrity ON with a real rogue ----------------------------------------
c = SimEngine("rush_50", seed=42, policy=SwarmPolicy(integrity=True))
c.run(20)
res = c.inject("ROGUE_ROBOT")
print("\ninject:", res)
target = res.get("robot_id")
for t in range(200):
    c.step()
    if c.policy.council.is_contained(target):
        print(f"  contained at tick {c.tick} (injected ~20)")
        break
s = c.policy.stats()["integrity"]
print("  contained:", s["council"]["contained"])
print("  pending:", list(s["council"]["pending"])[:3])
print("  accusations:", s["council"]["accusations"])
print("  events:", s["council"]["events"][:1])
r = c.robots[target]
print(f"  {target} quarantined={r.quarantined} v={r.velocity:.2f} task={r.current_task_id}")
print("  false positives:", [x for x in s["council"]["contained"] if x != target])
