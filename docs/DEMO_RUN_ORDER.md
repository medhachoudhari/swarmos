# SWARMOS - Live Demo Run Order

SIH26123 - Edge-AI Based Distributed Fleet Coordination for AMRs in Smart
Warehouses. Sponsor: Bharat Electronics Limited. Theme: Robotics & Drones.

Target length: **5 minutes of demo + 3 minutes of Q&A.** Every beat below has a
time budget, a single sentence to say, and an exact click. Do not improvise new
clicks - anything not in this list is a risk you have not rehearsed.

---

## 0. Before the judges arrive (T-10 min)

```
cd /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920
./run.sh --demo
```

Then in the browser: `http://127.0.0.1:8770`

If demoing from a laptop over SSH, `run.sh` prints the exact tunnel line:

```
ssh -L 8770:127.0.0.1:8770 <host>
```

Pre-flight checklist - all five must be true before you present:

- [ ] Landing screen shows the AMR hero art and the wordmark glyph.
- [ ] Bottom strip reads `VERDICTS --` (a dash, never `NaN`).
- [ ] `./run.sh --test` has been run once today and printed 575 passed.
- [ ] Browser zoom is 100 pct, window is maximised, width >= 1400 px.
- [ ] Nothing else is bound to port 8770 (`./run.sh --check`).

Set the browser to full screen (F11). Close every other tab: a stray tab is the
single most common way a live demo looks unprofessional.

---

## 1. Beat 1 - the problem, on the landing screen (0:00 - 0:30)

**Do:** nothing. Leave the landing screen up.

**Say:** "A smart warehouse runs dozens of autonomous mobile robots in aisles
narrower than two robots. The hard part is not navigation, it is what happens
when two robots want the same square metre at the same moment, and the network
between them is unreliable. SWARMOS is the coordination layer that decides that,
on the edge, in under 100 milliseconds per tick."

Point at the dashed ring in the hero art: "that is the 15 metre radio horizon -
every robot decides using only what it can hear."

---

## 2. Beat 2 - start the run (0:30 - 1:15)

**Do:** click **Start demo run**.

**Say:** "rush_50 scenario, seed 11, fleet of 8. Ten ticks per second." As the
robots appear: "colour here means state and nothing else - amber is waiting,
red is blocked, blue is charging, teal is a sovereign agent."

Let it run. Point at the hero metric: "tasks per minute, top left, is the number
the warehouse operator actually cares about."

**If it does not start:** the Lab tab now reports the server's real reason in
plain English. Read it out loud - that is a feature, not a stumble.

---

## 3. Beat 3 - a conflict, resolved (1:15 - 2:00)

**Do:** click any robot that is amber or red to select it. Its trail appears.

**Say:** "That robot is yielding. It is not yielding because a central server
told it to - it is yielding because the safety arbiter on board decided the
other robot has the stronger claim, and that decision is binding. The machine
learning layer can advise, but it can never override this. That separation is
structural in the code, not a policy we promise to follow."

Point at VERDICTS in the bottom strip: "every one of those is an arbiter
decision, counted."

---

## 4. Beat 4 - inject a fault (2:00 - 3:00)

**Do:** Lab tab -> inject a fault on a robot that is mid-aisle.

**Say:** "A real fleet degrades. I am going to fail a robot in the middle of a
narrow aisle." Watch the fleet reroute. "Nobody stopped. The others detected the
silence within 200 milliseconds and replanned around a static obstacle."

Then, the strongest beat for a BEL panel:

**Do:** inject the rogue / adversarial fault.

**Say:** "Now a worse case: a robot that is not dead but is misbehaving -
ignoring the protocol. Defence customers care about this far more than about
throughput. SWARMOS contains it: the neighbours quarantine the offender and keep
working. That is our most novel contribution."

---

## 5. Beat 5 - the honest measurement (3:00 - 4:15)

**Do:** Compare tab (X-12, counterfactual co-simulation).

**Say:** "This is the same warehouse, same seed, same task list, run twice: once
with SWARMOS arbitration and once with a baseline. Identical up to the tick where
the two policies first disagree - and we show you that tick."

Then, deliberately: "Two results, and I will give you both.

Zero collisions in 27 paired 9000-tick runs - that criterion is met. But the
baseline also scored zero, so zero collisions proves we are safe, not that we are
better.

Our throughput target was 20 percent over baseline. We measured minus 19 percent,
with a 95 percent confidence interval of minus 36 to minus 3. We did not hit it,
and we are telling you rather than picking a friendlier chart. We also found out
why: in these scenarios the task supply runs out before the run does, so the
comparison is measuring an empty warehouse, and `avg_completion_s` is
survivorship-biased - a policy that finishes 3 tasks looks 'faster' than one that
finishes 12. Fixing the statistic is our next work item, and it is written up in
`docs/SUCCESS_CRITERIA_VERIFICATION.md`."

This beat wins more credit than a fake win would. Judges have seen dozens of
teams claim a round improvement number with n=1.

---

## 6. Beat 6 - determinism, the closing line (4:15 - 5:00)

**Do:** Analytics tab, point at the trace hash.

**Say:** "Every run emits a trace hash. Same scenario and same seed gives a
byte-identical hash, so any incident in this system can be replayed exactly.
For a safety-critical fleet that is the difference between a bug report and an
investigation. 575 automated tests, six modules, and the coordination decision
budget is 100 milliseconds a tick with measured headroom."

Stop talking. Invite questions.

---

## Recovery moves

| Symptom | Move |
| --- | --- |
| Page shows a degraded banner about frames | It is telling the truth; say "the UI reports staleness rather than freezing a stale picture" and press Start again. |
| Nothing renders | Reload the tab. Engine state is server side; the run survives. |
| Port busy | `./run.sh --check`, then `./run.sh --demo 8771`. |
| A judge asks for a scenario you have not rehearsed | Lab tab, `narrow_aisle_deadlock`, fleet 24. Say what you expect to see before you press Start. |

## What never to do on stage

- Do not claim the 20 percent throughput target was met.
- Do not call the ML layer a safety feature. It is advisory, by design.
- Do not resize the window mid-demo.
- Do not open a code editor. If asked, open the file they asked for and nothing else.
