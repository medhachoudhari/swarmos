# SWARMOS - Judge Q&A Sheet

SIH26123, sponsor Bharat Electronics Limited. Read this the night before, not on
stage. Answers are short on purpose: a 20-second answer that names a file is
stronger than a 90-second answer that names nothing.

Two rules that apply to every answer below:

1. **Never invent a number.** If you do not know it, say "I do not have that
   measured" and name the file where it would live. Every measured number in this
   sheet exists in the repository.
2. **Never oversell the ML.** It is advisory. Saying so is a design strength.

---

## Tier 1 - almost certain to be asked

**Q. What is actually new here? Multi-robot path planning is a solved field.**

Path planning is solved; we use WHCA* and Contract Net, both standard, and we say
so. Three things are ours:

- **Adversarial robot containment** - not a failed robot, a robot that is alive
  and violating the protocol. The neighbours quarantine it and the fleet keeps
  working. We have not found this in the AMR literature and it is the part a
  defence customer cares about most.
- **Runtime assurance separation** - the ML advises, a deterministic arbiter
  decides, and the ML is structurally prevented from entering the safety path.
  This is Simplex architecture (Sha, 2001) applied to fleet coordination.
- **Deterministic replay** - every run emits a trace hash; same seed gives a
  byte-identical hash, so an incident can be replayed exactly.

**Q. Show me the improvement over a baseline.**

Open the Compare tab. Zero collisions across 27 paired 9000-tick runs - met. On
throughput we targeted plus 20 percent and measured **minus 19 percent, 95
percent CI [minus 36, minus 3]**. We did not hit it. We also know why, and the
reason is a measurement bug, not a hand-wave: the task supply is exhausted before
the run window closes, so the second half of the comparison is an empty
warehouse, and `avg_completion_s` is survivorship-biased - an arm that completes 3
tasks scores "faster" than one that completes 12. Re-scoring on `tasks_per_min`
with matched completion counts is our next work item. It is all written up in
`docs/SUCCESS_CRITERIA_VERIFICATION.md`.

**Q. So your system is slower. Why would anyone deploy it?**

Because the throughput number we currently report is not measuring throughput, it
is measuring an artefact, and we will not claim a win on a statistic we do not
trust. What we can defend today: zero collisions, a bounded 100 ms decision
budget with measured headroom, graceful degradation under robot failure, and
containment of a misbehaving robot. In a warehouse, one collision costs more than
a few percent of throughput.

**Q. Where is the AI? This looks like classical algorithms.**

There is a learned congestion forecaster that predicts where the warehouse will
jam and biases task assignment away from it. It is deliberately advisory: it can
change which task a robot takes, it can never change whether a robot is allowed
to move into an occupied cell. If you disable it, the fleet is slower but exactly
as safe. That is the property we wanted.

**Q. Is this centralised or distributed?**

Decisions are local: each robot uses only neighbours inside a 15 m radio horizon,
with 10 Hz heartbeats, 200 ms suspicion and 500 ms confirmation. The single
process you are looking at is the simulator hosting all of them, not a central
brain. The coordination code takes no global state it could not obtain over radio.

---

## Tier 2 - likely

**Q. Real robots or simulation only?**

Simulation only, and we will not pretend otherwise. The coordination layer takes
pose, battery and task state and returns a motion verdict - that interface is what
a ROS 2 node would supply. Porting means replacing the state source, not
rewriting the policy.

**Q. How many robots does it scale to?**

We demo fleet 8 because that is our measured parity point. The scenarios go to 50
(`rush_50`). The cost driver is neighbours within 15 m, not fleet size, so the
per-robot cost is roughly constant as the warehouse grows with the fleet. What we
have not done is a scaling study to 500 - do not claim one.

**Q. Can it run on the robot? "Edge AI" is in the problem statement.**

The decision budget is 100 ms per tick and the Analytics tab shows the measured
p50/p95/p99 against it. It is integer and float arithmetic over a handful of
neighbours - no GPU. We have not measured it on an actual embedded target, so we
quote headroom on this machine, not a board.

**Q. What happens if the network partitions?**

Each side keeps coordinating within itself, because the protocol never needed the
other side. Robots that go silent are treated as static obstacles after
confirmation, which is the conservative choice - you route around them rather
than assuming they moved.

**Q. Deadlock - two robots facing each other in a one-wide aisle?**

Try it: `narrow_aisle_deadlock`, fleet 24, in the Lab tab. Detection uses the
Coffman conditions over the wait-for graph; resolution breaks the cycle by
revoking the weaker claim. The arbiter's decision is binding, so there is no
oscillation.

**Q. How do you know the simulator is not just agreeing with you?**

Three ways. The simulator is the single source of robot state and the coordination
layer cannot write to it - it can only return verdicts. Collisions are measured
geometrically at 0.70 m, independent of the policy. And the baseline arm runs in
the same simulator, so a simulator that flattered us would flatter the baseline
too - which is exactly what happened: the baseline also scored zero collisions.

---

## Tier 3 - harder, be honest

**Q. Your 575 tests - what do they actually prove?**

They pin behaviour, not correctness. They cover the arbiter's decision table, the
failure detector timings, the deadlock cycle breaker, the API contract and the
determinism of the trace hash. They do not constitute a safety case. A real
deployment needs hardware-in-the-loop and a hazard analysis, and we have neither.

**Q. Team of five - who wrote what?**

Six modules: frontend, backend, ML, coordination, simulation, database and
analytics, with frozen interfaces in `docs/INTEGRATION_CONTRACTS.md`. Answer for
the module you own and hand over for the rest; do not narrate someone else's code.

**Q. Why build your own simulator instead of using Gazebo?**

Determinism and speed. We need thousands of 9000-tick runs to make a statistical
claim, and we need the same seed to give a byte-identical trace. A physics
simulator gives neither cheaply. The trade-off is that we do not model wheel slip,
sensor noise or dynamics - so our numbers are about coordination, not control.

**Q. Biggest weakness?**

The throughput claim is unproven and the measurement that produced it was flawed.
Second: no hardware. We would rather be asked about those than have them found.

---

## Numbers you may quote (all measured, all in the repo)

| Quantity | Value | Where |
| --- | --- | --- |
| Collisions, 27 paired 9000-tick runs | 0 | `docs/SUCCESS_CRITERIA_VERIFICATION.md` |
| Throughput vs baseline | -19.3 pct, CI [-36.0, -2.6] | same |
| Decision budget | 100 ms per tick, 10 Hz | `app/sim/clock.py` |
| Radio horizon | 15 m | `app/coordination/swarm_policy.py` |
| Failure detection | 200 ms suspicion, 500 ms confirmation | same |
| Collision threshold | 0.70 m centre to centre | `app/sim/engine.py` |
| Hard stop distance | 0.75 m | `app/coordination/swarm_policy.py` |
| Automated tests | 575 passing | `./run.sh --test` |
| Largest scenario | 50 robots (`rush_50`) | `app/sim/scenarios.py` |

## Three sentences never to say

- "It improves throughput by 20 percent." (It does not. We measured the opposite.)
- "The AI decides when robots should stop." (It never does. The arbiter does.)
- "It is production ready." (It is a simulator with no hardware validation.)
