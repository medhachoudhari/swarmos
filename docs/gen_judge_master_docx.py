#!/usr/bin/env python3
"""Generate SWARMOS_JUDGE_MASTER_DOCUMENT.docx.

One comprehensive Word document covering:
  1. Project overview
  2. Codebase / file organisation map
  3. Per-team-member "your part" guidance
  4. Full feature inventory with novelty ranking (from docs/gen_implementation_list_docx.py)
  5. Per-feature judge-demo guidelines (what to click, what to say, what judges will see)
  6. Baseline vs SWARMOS comparison - honest current numbers
  7. Known limitations, fixed 2026-09-22
  8. Anticipated judge Q&A

All numbers here are either lifted from code comments already in the repo
(cited by file) or freshly measured in this session (cited as "measured
2026-09-22"). Nothing here is invented.
"""
from __future__ import annotations

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = "SWARMOS_JUDGE_MASTER_DOCUMENT.docx"

NAVY = RGBColor(0x12, 0x1E, 0x33)
TEAL = RGBColor(0x1F, 0x7A, 0x6C)
GREY = RGBColor(0x55, 0x5F, 0x6B)


def set_cell_shading(cell, hex_color):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    cell._tc.get_or_add_tcPr().append(shd)


def h1(doc, text):
    p = doc.add_heading(text, level=1)
    for run in p.runs:
        run.font.color.rgb = NAVY
    return p


def h2(doc, text):
    p = doc.add_heading(text, level=2)
    for run in p.runs:
        run.font.color.rgb = TEAL
    return p


def h3(doc, text):
    p = doc.add_heading(text, level=3)
    return p


def body(doc, text, *, bold=False, italic=False, size=11):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    return p


def bullet(doc, text, *, level=0):
    p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    p.add_run(text)
    return p


def numbered(doc, text):
    p = doc.add_paragraph(style="List Number")
    p.add_run(text)
    return p


def code_block(doc, text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.font.name = "Consolas"
    r.font.size = Pt(9.5)
    p.paragraph_format.left_indent = Inches(0.3)
    return p


def make_table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.bold = True
        set_cell_shading(hdr[i], "1F2937")
        for p in hdr[i].paragraphs:
            for r in p.runs:
                r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    return t


def demo_block(doc, feature_name, what_it_is, files, action, see, say, qa):
    h3(doc, feature_name)
    body(doc, "What it is:", bold=True)
    body(doc, what_it_is)
    body(doc, "Where it lives in the code:", bold=True)
    body(doc, files)
    body(doc, "Exact live-demo action:", bold=True)
    body(doc, action)
    body(doc, "What the judge should see on screen:", bold=True)
    body(doc, see)
    body(doc, "The one sentence to say out loud:", bold=True)
    p = doc.add_paragraph()
    r = p.add_run('"%s"' % say)
    r.italic = True
    body(doc, "Anticipated judge question + answer:", bold=True)
    body(doc, "Q: %s" % qa[0], italic=True)
    body(doc, "A: %s" % qa[1])
    doc.add_paragraph()


def main():
    doc = Document()

    # Base style
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # ------------------------------------------------------------------ title
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("SWARMOS")
    r.font.size = Pt(40)
    r.bold = True
    r.font.color.rgb = NAVY

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run("Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots")
    r.font.size = Pt(15)
    r.font.color.rgb = TEAL

    sub2 = doc.add_paragraph()
    sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub2.add_run("Judge Master Document -- SIH26123 -- Team Member 4 (Coordination)")
    r.font.size = Pt(12)
    r.font.color.rgb = GREY

    sub3 = doc.add_paragraph()
    sub3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub3.add_run("Generated 2026-09-22")
    r.font.size = Pt(10)
    r.font.color.rgb = GREY
    doc.add_page_break()

    # ------------------------------------------------------------------ TOC-ish overview
    h1(doc, "1. Project Overview")
    body(doc,
        "SWARMOS is a distributed fleet-coordination system for autonomous mobile "
        "robots (AMRs) in a smart warehouse. Up to 50 robots pick and drop tasks on "
        "a simulated warehouse floor, coordinated by a decentralized negotiation "
        "layer (the swarm policy), backstopped by a hard safety kernel that never "
        "trusts the negotiation, with an edge-AI advisory layer strictly outside "
        "the safety path, and a live web dashboard for operators and judges.")
    body(doc,
        "The core engineering claim is a Simplex-style runtime-assurance "
        "architecture: an Advisory layer proposes, a deterministic Binding safety "
        "kernel decides, and the Applied motion is what the simulation actually "
        "executes. Killing the ML advisory layer live, mid-run, changes nothing "
        "about collision safety -- this is provable on stage, not just claimed.")
    bullet(doc, "10 Hz tick-based simulation, deterministic replay from (scenario, seed)")
    bullet(doc, "Verdict ladder: PROCEED / SLOW / YIELD / WAIT / REROUTE")
    bullet(doc, "Hard safety floor at 0.75 m, enforced independently of the negotiation")
    bullet(doc, "Live fault injection: robot failure, comm blackout, battery drain, "
                "aisle blockage, rogue/lying robot, link impairment, task burst, kill-ML")
    bullet(doc, "Paired counterfactual comparison against a classical stop-and-wait baseline")
    bullet(doc, "Native ES modules web dashboard: no build step, no bundler")

    # ------------------------------------------------------------------ file map
    h1(doc, "2. Codebase / File Organisation Map")
    body(doc, "Top-level layout:")
    make_table(doc, ["Path", "Owns"], [
        ["app/sim/", "The M5 simulation: engine.py (tick loop), robot.py, scenarios.py, "
                     "warehouse.py, pathfinding.py, tasks.py, policy.py (baseline + verdict types)"],
        ["app/coordination/", "The M4 arbiter: swarm_policy.py (negotiation ladder + safety "
                               "monitor), integrity.py (X-10/N9 rogue detection), models.py"],
        ["app/ml/", "M3: forecast.py, the advisory-only congestion forecaster"],
        ["app/db/", "M6: schema.py, store.py, stats.py, benchmark.py -- persistence and "
                     "the paired-comparison statistics engine"],
        ["app/api/", "M2: server.py (Starlette app, websocket + REST), runner.py "
                      "(SimEngine/policy factory), cosim_runner.py, cosim_api.py"],
        ["web/", "M1: the dashboard. js/main.js (bootstrap), map.js (canvas renderer), "
                  "palette.js, transport.js, store.js, panels/*.js; styles/*.css; "
                  "landing.html + index.html"],
        ["tests/", "576 pytest tests -- the evidence behind every measured claim"],
        ["tools/", "diagnostic and measurement scripts (diag_*.py), one-off patch "
                    "scripts used during development (patch_*.py), verify_*.py "
                    "criteria/contract checkers"],
        ["docs/", "specification, session summaries, and this document"],
    ], widths=[1.6, 5.0])

    body(doc,
        "Tick order (fixed, documented at the top of app/sim/engine.py, and load-bearing "
        "for the determinism guarantee): "
        "(1) apply due fault injections, (2) generate new tasks, (3) dispatch pending "
        "tasks to eligible robots, (4) plan/replan paths, (5) publish state, arbitrate, "
        "apply verdicts, (6) integrate motion for one dt, (7) resolve pickups/drops/"
        "charging, (8) account safety invariants and update the rolling trace hash.")

    # ------------------------------------------------------------------ per member
    h1(doc, "3. Per-Team-Member Guidance")
    body(doc,
        "Based on the module ownership already recorded in "
        "docs/gen_project_blueprint_docx.py. Each member should be able to open "
        "their module's file(s), point at the exact function backing their claim, "
        "and answer 'why does this exist' in one sentence.")

    members = [
        ("Nandita -- M1 Frontend / UI-UX", "web/",
         "Live digital-twin command centre (N7). Explain: this is NOT claimed as "
         "a research novelty -- a UI is not a technical contribution. What IS "
         "defensible is that the UI renders the coordination REASONING, not just "
         "robot positions: the Decision Inspector shows the actual utility "
         "margin that decided a contest, live.",
         "Open the Decision tab, select a moving robot, and read out the "
         "utility_terms and winning_margin fields out loud."),
        ("<owner> -- M2 Backend API", "app/api/",
         "The websocket/REST seam and the policy factory (_make_policy). Explain "
         "the schema-version check on hello frames and why the baseline policy "
         "deliberately has no integrity API (fairness of the comparison).",
         "Show the /api/scenarios and /api/sim/start endpoints in the Lab tab "
         "network trace; explain start/pause/resume/step/stop are the whole "
         "control surface."),
        ("Medha -- M3 AI / ML", "app/ml/forecast.py",
         "Edge-AI advisory layer (N5, GENUINE -- this is Simplex runtime "
         "assurance, Sha 2001). Explain: the forecaster's output is written to "
         "the snapshot for display and is NEVER passed to the policy -- deleting "
         "it or feeding it garbage cannot change robot behaviour or the trace "
         "hash, and tests/test_ml_fence.py proves that mechanically, not just by "
         "convention.",
         "Fire the Kill ML fault live. Show collisions stay at 0 and the map "
         "keeps moving exactly the same."),
        ("Adithya -- M4 Robotics / Multi-Agent (this module)", "app/coordination/",
         "The verdict ladder (N4), the safety monitor (N5's enforcement half), "
         "and adversarial containment (N9, GENUINE-NEW). Explain the graded "
         "ladder PROCEED/SLOW/YIELD/WAIT/REROUTE and why the monitor is "
         "deliberately 'dumber' than the negotiation above it (auditability).",
         "Inject a rogue robot (spoofed position), show the dashed 'lie line' "
         "on the map, and narrate the quorum containment and throughput "
         "recovery."),
        ("Kushi -- M5 Simulation", "app/sim/",
         "The 50-robot scenario suite, warehouse geometry, task generator, and "
         "the fault-injection framework. Explain the WIP admission-control cap "
         "(X-28) and why releasing every task at once collapses throughput.",
         "Run the fleet sweep (tools/diag_gridlock_sweep.py) live or show the "
         "saved output; explain why fleet 16 is the measured throughput peak."),
        ("Harshita -- M6 Database / Analytics", "app/db/",
         "Persistence and the paired-comparison statistics engine (stats.py, "
         "benchmark.py). Explain the sign convention (delta = baseline minus "
         "treatment) and why seeds whose baseline completed zero tasks are "
         "excluded and REPORTED, not silently dropped.",
         "Open the Compare tab, run a paired comparison, and read the excluded "
         "seeds list out loud if any exist."),
    ]
    for name, path, claim, action in members:
        h3(doc, name)
        body(doc, "Primary file(s): %s" % path, italic=True)
        body(doc, "Core claim to own: %s" % claim)
        body(doc, "Suggested 30-second demo beat: %s" % action)

    # ------------------------------------------------------------------ full feature inventory
    h1(doc, "4. Full Feature Inventory and Novelty Ranking")
    body(doc,
        "This ranking already exists in the codebase "
        "(docs/gen_implementation_list_docx.py) and reflects an internal "
        "adversarial review, not marketing copy. Presenting it AS-IS to judges "
        "is itself a credibility move: it shows the team can distinguish real "
        "novelty from standard practice.")

    novelty_rows = [
        ("N1", "Decentralised auction task allocation", "INCREMENTAL - stated honestly",
         "Contract Net Protocol (Smith 1980). Compete on measured result, not the idea."),
        ("N2", "Intent broadcast + space-time reservation", "TABLE STAKES",
         "WHCA* (Silver 2005) / Kiva-class practice. Kept as a measured invariant (X-09), not claimed novel."),
        ("N3", "Deterministic replay", "GENUINE (engineering)",
         "Rolling trace hash; two instances diffed live prove identical seeds -> identical outcome."),
        ("N4", "Deadlock detection, graded response ladder", "INCREMENTAL",
         "Classical wait-for cycle detection (Coffman/Knapp). Ladder visibility per decision is the value-add."),
        ("N5", "Edge-AI advisory behind a hard safety firewall", "GENUINE",
         "Simplex architecture (Sha 2001). Contribution is the enforcement + live measurement, not the idea."),
        ("N6", "Graceful degradation ladder", "INCREMENTAL",
         "Standard fault-tolerant design; only counts because degradation is OBSERVED under injected packet loss."),
        ("N7", "Live digital-twin command centre", "DIFFERENTIATION, not novelty",
         "A UI is not a technical contribution; the defensible part is rendering the reasoning, not the pixels."),
        ("N9", "Adversarial robot containment", "GENUINE - NEW",
         "Byzantine-tolerant task allocation; rare in hackathon entries; strong fit for a defence sponsor."),
        ("N10", "Counterfactual co-simulation", "GENUINE - NEW",
         "Identical seed/task stream run against baseline and SWARMOS side by side -- a fair, falsifiable comparison."),
    ]
    make_table(doc, ["Tag", "Feature", "Honesty rating", "Why"], novelty_rows,
               widths=[0.5, 1.8, 1.3, 3.0])

    body(doc, "")
    body(doc, "Deferred (correct, but not load-bearing for this build):", bold=True)
    for tag, name, _sz, reason in [
        ("X-05", "Congestion-aware time-expanded cost field",
         "M", "Advisory-only forecaster exists; not promoted into the planner (measured to underperform persistence)."),
        ("X-06", "Deadlock avoidance via priority inheritance", "M",
         "Detection + ladder + failure handling already give a recoverable system."),
        ("X-11", "Operator authority with audit trail", "M",
         "Competes with X-10/N9 for the same build days; N9 is the stronger claim."),
        ("X-15", "Sensing-reality knob", "M", "Hooks exist in M5; live UI controls deferred."),
    ]:
        bullet(doc, "%s -- %s: %s" % (tag, name, reason))

    body(doc, "")
    body(doc, "Explicitly rejected or withdrawn (say this OUT LOUD if asked -- it is a strength, not a weakness):", bold=True)
    for tag, name, reason in [
        ("X-07", "Bounded windowed CBS conflict-tree replan",
         "All four internal reviewers ranked it last; a half-built optimal search is worse than a clearly scoped absence."),
        ("A-02", "RandomForest action classifier trained on rule outputs",
         "Deleted outright: behaviour-cloning our own rule engine caps the model at the rules."),
        ("N8", "Closed-loop analytics into bid weights",
         "As specified it was offline tuning with a feedback arrow drawn on a slide. Claim withdrawn rather than defended."),
    ]:
        bullet(doc, "%s -- %s: %s" % (tag, name, reason))

    # ------------------------------------------------------------------ per-feature demo guidelines
    h1(doc, "5. How to Demonstrate Each Feature to Judges")
    body(doc,
        "Every feature below follows the same six-part structure so any team "
        "member can present any feature under pressure: what it is, where it "
        "lives, the exact click sequence, what appears on screen, the one line "
        "to say, and the most likely pushback with its answer.")

    demo_block(doc,
        "N5 / X-09 -- Simplex safety kernel (Advisory / Binding / Applied)",
        "An ML advisory layer proposes speed reductions; a small, auditable "
        "safety kernel independently decides the final verdict; the simulation "
        "only ever executes the kernel's decision.",
        "app/ml/forecast.py (Forecaster.advise), app/coordination/swarm_policy.py "
        "(SwarmPolicy._monitor), app/sim/engine.py (SimEngine._advise / "
        "_apply_verdicts).",
        "Open Command Palette (Ctrl+K) -> 'Start run'. Once ticking, open the "
        "Command Palette again and fire the Kill ML fault (or use the Lab "
        "panel's fault picker). Watch the KPI strip and the map for the next "
        "30 seconds.",
        "The Collisions KPI stays at 0 before and after; robots keep moving "
        "identically; the Decision Inspector still shows verdicts (WAIT/YIELD/"
        "SLOW/PROCEED/REROUTE), just with no advisory attached.",
        "Killing the AI right now changes nothing about safety -- the kernel "
        "that actually stops robots from colliding was never the AI in the "
        "first place.",
        ("Isn't this just turning a feature off? What does it actually prove?",
         "It proves the safety-critical path has zero dependency on the "
         "learned component -- tests/test_ml_fence.py enforces this "
         "mechanically at the code level, not just as a demo trick."),
    )

    demo_block(doc,
        "Verdict ladder -- PROCEED / SLOW / YIELD / WAIT / REROUTE",
        "Instead of a binary stop/go, the arbiter grades its intervention: slow "
        "down, yield right of way, hold, or replan -- only escalating to a full "
        "stop when nothing else is safe.",
        "app/coordination/swarm_policy.py (SwarmPolicy._decide, ._contest, "
        "._monitor), app/sim/policy.py (VerdictKind enum).",
        "Open the Decision tab and select any two robots approaching each "
        "other in a crossing aisle.",
        "The verdict kind and its reason string (e.g. 'crossing R012 at 1.10 m') "
        "update live per robot; watch one SLOW down rather than stop dead.",
        "This grading is why we beat stop-and-wait on throughput -- the "
        "biggest single source of the gap is that a mere crossing gets a SLOW, "
        "not a full stop.",
        ("Why not just always stop to be maximally safe?",
         "We measured it: an always-stop kernel vetoed 35% of all robot-ticks "
         "and wedged head-on traffic completely, because neither robot was "
         "privileged and the aisle never cleared. Grading is what makes the "
         "system both safe AND fast."),
    )

    demo_block(doc,
        "N9 / X-10 -- Adversarial robot containment",
        "A robot can be turned rogue: it broadcasts a false position. The "
        "quorum-based integrity layer detects the mismatch between the claim "
        "and what peers actually observe, and contains (quarantines) the liar.",
        "app/coordination/integrity.py (quorum containment), app/sim/engine.py "
        "(_fault_rogue, apply_containment).",
        "Open Command Palette -> inject the Rogue Robot fault on a visible, "
        "moving robot.",
        "A dashed line appears from the robot's real body to its claimed "
        "(false) position -- the gap IS the evidence. Within a few ticks the "
        "robot's ring turns to the quarantined colour and its task is released "
        "back to the pool.",
        "That gap you see is the lie, and the system caught it without any "
        "central authority -- just its peers' own honest sightings.",
        ("How do you know a HONEST robot with sensor noise won't get "
         "quarantined by mistake?",
         "The claim tolerance is set well beyond realistic sensor noise but "
         "well inside the danger threshold -- the rogue fault's default offset "
         "(2.5 m) is chosen specifically to be outside that tolerance."),
    )

    demo_block(doc,
        "X-01 -- Sovereign mode (communications blackout survival)",
        "A robot that has heard zero peers for half a second assumes it cannot "
        "trust the negotiation any more. Instead of stopping, it keeps working "
        "under a WIDER safety envelope and a capped speed, and rejoins the "
        "moment it hears a peer again.",
        "app/coordination/swarm_policy.py (SwarmPolicy._update_sovereign, "
        "SOVEREIGN_MARGIN_M, SOVEREIGN_SPEED_CAP), app/sim/engine.py "
        "(_fault_comm_blackout, _sync_sovereign).",
        "Inject Comm Blackout on a moving robot from the palette.",
        "That robot's safety ring visibly widens and it visibly slows, but "
        "keeps moving instead of freezing in the aisle; after ~6 seconds it "
        "rejoins and the ring returns to normal.",
        "Less information means more caution, not a dead stop -- the robot "
        "widens its own safety margin instead of blocking the aisle for "
        "everyone else.",
        ("Isn't a robot moving blind more dangerous than stopping it?",
         "No -- a stopped robot blocking an aisle causes its own hazard for "
         "every other robot. The wider floor and capped speed are measured to "
         "still hold the same zero-collision invariant."),
    )

    demo_block(doc,
        "N10 -- Counterfactual co-simulation (Compare tab)",
        "The classical stop-and-wait baseline and SWARMOS run on the IDENTICAL "
        "seed and task stream, side by side, so the comparison is paired and "
        "fair rather than two independent runs that happened to differ.",
        "app/sim/cosim.py, app/api/cosim_runner.py, web/js/panels/cosim.js.",
        "Open the Compare tab, pick a scenario and seed, press Start.",
        "Both fleets render on the same map (SWARMOS solid, baseline ghosted); "
        "the KPI delta panel updates live with the paired reduction percentage.",
        "Same warehouse, same tasks, same seed -- the only variable that "
        "changed is the coordination brain.",
        ("What is the honest current result of this comparison?",
         "See section 6 below -- as of 2026-09-22 the throughput-time "
         "reduction criterion (target >=20%) is measured NOT MET, mean +2.0%, "
         "95% CI [-5.9%, +9.8%]. We report this directly rather than hide it."),
    )

    # ------------------------------------------------------------------ baseline comparison honest numbers
    h1(doc, "6. Baseline vs SWARMOS -- Honest Current Comparison")
    body(doc,
        "This directly answers the question 'why does baseline sometimes beat "
        "SWARMOS, and what is the point of SWARMOS then'.")
    body(doc, "What 'baseline' is:", bold=True)
    body(doc,
        "StopAndWaitPolicy (app/sim/policy.py) -- the classical AGV controller: "
        "no negotiation, no reservations, no joint planning, no learning. If a "
        "conflict is detected, stop. It is deliberately tuned to be a FAIR "
        "reference, not a strawman -- it uses the same HARD_STOP_M=0.75 m safety "
        "floor SWARMOS uses, and its own STUCK_TICKS recovery threshold was "
        "swept and tuned rather than left at an arbitrary default.")

    body(doc, "Measured result, 2026-09-22 (tools/verify_criteria_powered.py, 1800 ticks, seeds 11/13/17, 3 scenarios):", bold=True)
    make_table(doc, ["Scenario (fleet)", "Seed", "Baseline avg_completion_s", "SWARMOS avg_completion_s", "Reduction"], [
        ["blocked_aisle (40)", "11", "102.30", "103.85", "-1.5%"],
        ["blocked_aisle (40)", "13", "96.48", "84.27", "+12.7%"],
        ["blocked_aisle (40)", "17", "87.30", "78.68", "+9.9%"],
        ["narrow_aisle_deadlock (24)", "11", "76.87", "79.28", "-3.1%"],
        ["narrow_aisle_deadlock (24)", "13", "81.70", "78.52", "+3.9%"],
        ["narrow_aisle_deadlock (24)", "17", "117.48", "112.37", "+4.3%"],
        ["rush_50 (50)", "11", "89.34", "106.68", "-19.4%"],
        ["rush_50 (50)", "13", "85.20", "87.58", "-2.8%"],
        ["rush_50 (50)", "17", "100.54", "86.75", "+13.7%"],
    ], widths=[1.9, 0.5, 1.4, 1.4, 1.0])
    body(doc,
        "Paired mean reduction: +2.0% (std dev 10.3%, 95% CI [-5.9%, +9.8%]). "
        "Target for the throughput-time criterion is >=20%. Verdict: NOT MET -- "
        "the whole confidence interval sits below the bar.")

    body(doc, "Why baseline sometimes wins on raw completion time:", bold=True)
    bullet(doc, "The graded ladder trades a guaranteed full stop for negotiated "
                "give-way. On some seeds this genuinely produces a faster "
                "resolution; on others the negotiation overhead (contests, "
                "commit windows) costs more time than a simple stop would have.")
    bullet(doc, "The gridlock defect fixed on 2026-09-22 (see section 7) was "
                "artificially depressing SWARMOS numbers at fleet 40-50 before "
                "today -- those specific runs above were re-measured AFTER the "
                "fix, and the comparison is now honest rather than gridlock-"
                "contaminated.")
    bullet(doc, "avg_completion_s is a small-sample statistic at 1800 ticks "
                "(3-26 completions per arm per run) -- the CI in the table above "
                "is wide because the sample is genuinely small, not because the "
                "measurement is broken. tools/verify_criteria_powered.py exists "
                "specifically to widen the sample (9000 ticks, 9 seeds).")

    body(doc, "So what IS the point of SWARMOS, if C2 is not currently met?", bold=True)
    bullet(doc, "C1 (zero collisions under full arbitration) is MET: 0 "
                "collisions in the SWARMOS arm across every measured run, "
                "against a baseline that also holds 0 here because it is "
                "equally conservative -- the honest comparison is on WHERE "
                "each policy spends its caution, not just the collision count.")
    bullet(doc, "The real differentiators are the capabilities baseline "
                "structurally cannot have at all: it has no integrity layer "
                "(defenceless against a lying robot, N9), no advisory-firewall "
                "architecture to demonstrate (N5), no counterfactual replay for "
                "auditability (N3), and no degradation ladder under packet loss "
                "(N6). These are qualitative, structural claims, not a single "
                "completion-time number.")
    bullet(doc, "The throughput claim is not abandoned -- it is reported "
                "honestly as NOT YET MET, with the exact gap (need +18pp) and "
                "the exact next step specified in "
                "docs/SUCCESS_CRITERIA_VERIFICATION.md and reproducible with "
                "tools/verify_criteria_powered.py.")

    # ------------------------------------------------------------------ limitations fixed today
    h1(doc, "7. Known Limitations -- Fixed This Session (2026-09-22)")
    h3(doc, "The fleet-50 permanent gridlock defect")
    body(doc,
        "At high fleet density, a pair of robots could land inside each "
        "other's safety floor and never recover: the safety monitor's own "
        "documented limitation is that once inside the floor, no fraction of a "
        "step clears it, so the pair cycled WAIT -> REROUTE -> WAIT forever, "
        "holding their tasks and permanently retiring fleet capacity. Measured "
        "before the fix: completions froze at 5-10 for the rest of a 14000-tick "
        "run while pending tasks grew unbounded to 2000+.")
    body(doc,
        "Fix: app/sim/engine.py now tracks per-robot net displacement while a "
        "task is held (SimEngine._check_stalls); if a robot makes less than "
        "2 cm of progress for 150 ticks (15 s), its task is released back to "
        "the pending pool -- the same 'release, don't loop forever' recovery "
        "the baseline already uses. This never touches the safety kernel's "
        "geometry (which was tuned five times previously and rejected each "
        "time for costing collisions) -- it only bounds how long a robot may "
        "keep retrying a standoff the kernel cannot itself resolve.")
    body(doc,
        "Verified: worst observed stall streak across a 6000-tick run at "
        "fleet 50 was exactly 150 ticks (the bound), never exceeded; 0 "
        "collisions; now covered by a permanent regression test "
        "(tests/test_sim_engine.py::test_no_robot_stalls_forever_at_high_density). "
        "Full write-up: docs/GRIDLOCK_DEFECT_20260922.md.")

    h3(doc, "UI defects fixed")
    bullet(doc, "Landing page ENTER SWARMOS button did nothing when the file "
                "was opened directly via file:// -- added a guard that detects "
                "this and tells the operator to run ./run.sh instead.")
    bullet(doc, "Map cursor-coordinate readout always showed '--, -- m' "
                "regardless of mouse position -- map.toWorld() returns a plain "
                "[x, y] array, but the readout code was reading it as an {x, y} "
                "object; fixed in web/js/main.js.")
    bullet(doc, "Command Palette (Ctrl+K) and Start/Resume were reported as "
                "not working -- verified with a headless-Chrome CDP script "
                "(tools/diag_palette_cursor.py) that the palette and every "
                "command work correctly when the app is served over http; the "
                "most likely cause of the report is the same file:// issue as "
                "the landing page.")

    # ------------------------------------------------------------------ Q&A
    h1(doc, "8. Anticipated Judge Q&A (General)")
    qa_general = [
        ("Why do you need fault injection if the system is supposed to "
         "self-heal?",
         "Fault injection is not the system cheating to avoid deadlock -- it is "
         "the mechanism to PROVE resilience on demand, live, in front of "
         "judges, instead of waiting for a random failure to happen during a "
         "5-minute demo window. Each fault (robot failure, comm blackout, "
         "battery drain, aisle block, rogue robot, link impairment) maps to "
         "exactly one specific claim in the code (see the FaultKind docstring "
         "in app/sim/scenarios.py)."),
        ("Why does the blocked_aisle scenario show robots stopped in a line?",
         "That is the scenario doing its job on purpose: it seals a corridor "
         "mid-run specifically to demonstrate reroute and the verdict ladder. "
         "The correct behaviour to show judges is the fleet detecting the "
         "block and visibly rerouting around it, not sitting frozen -- if it "
         "looks frozen for more than a few seconds, that IS the gridlock "
         "defect fixed in section 7."),
        ("Is any of this actually novel, or is it all standard practice?",
         "We answer this directly rather than deflect: N1/N2/N4/N6 are "
         "honestly rated INCREMENTAL or TABLE STAKES against named prior art "
         "(Contract Net Protocol, WHCA*, Coffman deadlock theory, standard "
         "fault-tolerant degradation). N3, N5, N9, N10 are rated GENUINE, with "
         "N9 (adversarial containment) and N10 (paired counterfactual "
         "co-simulation) rated GENUINE-NEW -- essentially absent from "
         "hackathon-scale multi-robot entries."),
        ("What happens if two robots' claims about who has right of way "
         "conflict?",
         "The utility-based contest in SwarmPolicy._contest is run "
         "IDENTICALLY by both robots on the same two states, so they agree "
         "without exchanging another message; ties break on robot id, which "
         "is arbitrary but TOTAL and reproducible under replay."),
        ("How do you know the demo isn't cherry-picked?",
         "Every number in this document is reproducible by running the named "
         "tool script (tools/diag_*.py, tools/verify_*.py) against the "
         "checked-in seed. The comparison methodology itself "
         "(app/db/stats.py) documents its own sign convention and explicitly "
         "excludes and REPORTS seeds where a percentage improvement would be "
         "undefined, rather than silently dropping them."),
    ]
    for q, a in qa_general:
        body(doc, "Q: %s" % q, bold=True)
        body(doc, "A: %s" % a)
        doc.add_paragraph()

    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()

# File contains AI-generated response based on internal company sources
