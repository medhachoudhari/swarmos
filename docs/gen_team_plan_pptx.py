#!/usr/bin/env python3.11
"""
Generate SWARMOS_Team_Plan_SIH26123.pptx — the 6-member team plan deck.

Standalone: builds a dark industrial command-centre themed deck from scratch
using python-pptx, no external template required.

Usage:
    /pkg/fs-foundation-/dynamic/bin/python3.11 docs/gen_team_plan_pptx.py

Output:
    SWARMOS_Team_Plan_SIH26123.pptx  (repo root)
"""

from __future__ import annotations

import os

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

# ------------------------------------------------------------------ theme

BG = RGBColor(0x12, 0x16, 0x1C)          # graphite
PANEL = RGBColor(0x1B, 0x21, 0x2A)       # slightly lighter panel
FG = RGBColor(0xE8, 0xEC, 0xF1)          # near white
MUTED = RGBColor(0x93, 0xA1, 0xB2)       # muted grey-blue
ACCENT = RGBColor(0x3B, 0x9E, 0xFF)      # blue
OK = RGBColor(0x35, 0xC7, 0x8A)          # green
WARN = RGBColor(0xF2, 0xB1, 0x37)        # amber
BAD = RGBColor(0xE5, 0x5B, 0x5B)         # red
VIOLET = RGBColor(0xA9, 0x7B, 0xFF)      # violet

W, H = Inches(13.333), Inches(7.5)

MEMBER_COLORS = {
    "M1": ACCENT, "M2": OK, "M3": VIOLET,
    "M4": WARN, "M5": RGBColor(0x4F, 0xD1, 0xC5), "M6": RGBColor(0xFF, 0x8A, 0x65),
}


def _txbox(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    return tf


def _set(p, text, size=14, color=FG, bold=False, space_after=4, font="Calibri"):
    p.text = text
    p.space_after = Pt(space_after)
    for r in p.runs:
        r.font.size = Pt(size)
        r.font.color.rgb = color
        r.font.bold = bold
        r.font.name = font


def _rect(slide, x, y, w, h, fill, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1.25)
    sh.shadow.inherit = False
    sh.text_frame.word_wrap = True
    return sh


def new_slide(prs, title, subtitle=None, accent=ACCENT):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG

    # accent bar
    from pptx.enum.shapes import MSO_SHAPE
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.09), H)
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent
    bar.line.fill.background()
    bar.shadow.inherit = False

    tf = _txbox(slide, Inches(0.45), Inches(0.28), Inches(12.4), Inches(0.9))
    _set(tf.paragraphs[0], title, size=28, bold=True, space_after=2)
    if subtitle:
        _set(tf.add_paragraph(), subtitle, size=13, color=MUTED)
    return slide


def bullets(slide, items, x=0.55, y=1.35, w=12.2, h=5.6, size=14, gap=6):
    """items: list of (text, indent_level) or plain strings."""
    tf = _txbox(slide, Inches(x), Inches(y), Inches(w), Inches(h))
    first = True
    for it in items:
        if isinstance(it, tuple):
            text, lvl = it[0], it[1]
            color = it[2] if len(it) > 2 else None
        else:
            text, lvl, color = it, 0, None
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = min(lvl, 4)
        bullet = "" if lvl == 0 and text.startswith(("[", "-", ">")) else ""
        col = color or (FG if lvl == 0 else MUTED)
        _set(p, f"{bullet}{text}", size=size - lvl, color=col,
             bold=(lvl == 0 and text.isupper()), space_after=gap)
    return tf


def table(slide, headers, rows, x=0.55, y=1.4, w=12.2, h=None,
          col_widths=None, size=11):
    nrows, ncols = len(rows) + 1, len(headers)
    h = h or Inches(0.32) * nrows
    gt = slide.shapes.add_table(nrows, ncols, Inches(x), Inches(y),
                                Inches(w), h).table
    if col_widths:
        total = Inches(w)
        s = sum(col_widths)
        for i, cw in enumerate(col_widths):
            gt.columns[i].width = Emu(int(total * cw / s))
    for c, htxt in enumerate(headers):
        cell = gt.cell(0, c)
        cell.text = htxt
        cell.fill.solid()
        cell.fill.fore_color.rgb = PANEL
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.size = Pt(size)
                r.font.bold = True
                r.font.color.rgb = ACCENT
    for ri, row in enumerate(rows, start=1):
        for ci, val in enumerate(row):
            cell = gt.cell(ri, ci)
            cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = BG if ri % 2 else PANEL
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(size)
                    r.font.color.rgb = FG
    return gt


def kpi_cards(slide, cards, y=1.6, h=1.5):
    """cards: list of (big, label, color)"""
    n = len(cards)
    gap = 0.25
    total = 12.2
    cw = (total - gap * (n - 1)) / n
    for i, (big, label, color) in enumerate(cards):
        x = 0.55 + i * (cw + gap)
        sh = _rect(slide, Inches(x), Inches(y), Inches(cw), Inches(h),
                   PANEL, line=color)
        tf = sh.text_frame
        tf.margin_left = Inches(0.15)
        tf.margin_top = Inches(0.12)
        _set(tf.paragraphs[0], big, size=30, color=color, bold=True,
             space_after=2)
        _set(tf.add_paragraph(), label, size=11, color=MUTED)


def note(slide, text, y=6.55, color=WARN):
    sh = _rect(slide, Inches(0.55), Inches(y), Inches(12.2), Inches(0.62),
               PANEL, line=color)
    tf = sh.text_frame
    tf.margin_left = Inches(0.18)
    tf.margin_top = Inches(0.08)
    _set(tf.paragraphs[0], text, size=12, color=FG, bold=True)


# ================================================================ content

MEMBERS = [
    {
        "id": "M1", "role": "Frontend / UI-UX",
        "mission": "Build the operational control centre: the screens that make "
                   "invisible coordination visible and demo-ready.",
        "features": [
            "Live Warehouse Command Center - map-first view, 50+ robots at 30 fps",
            "Fleet Overview - health, active robots, tasks, failures, KPIs",
            "Robot Detail - state, task, battery, path, decisions, peer context",
            "Decision Inspector - WHY a robot proceeded / waited / rerouted",
            "  including the counterfactual panel (N2): 'R12 would have won if...'",
            "Incident Center - conflicts, deadlocks, failures, blocked aisles",
            "Benchmark Center - baseline vs SWARMOS side by side",
            "Replay - scrub the timeline of an entire run",
            "Simulation Lab - scenario / robot count / fault injection controls",
        ],
        "files": [
            "frontend/src/screens/*            (one file per screen)",
            "frontend/src/map/WarehouseCanvas.tsx   (canvas/WebGL renderer)",
            "frontend/src/api/client.ts        (REST client, generated types)",
            "frontend/src/api/socket.ts        (WebSocket fleet stream)",
            "frontend/src/components/*         (shared UI primitives)",
        ],
        "consumes": "Fleet snapshot over WebSocket from M2 (~10 Hz); REST for "
                    "tasks/scenarios/benchmarks; AuctionDecision.utility_breakdown "
                    "for the Decision Inspector.",
        "produces": "User actions: create task, start/stop scenario, inject fault, "
                    "run benchmark, load replay.",
        "stack": "React 18 + TypeScript + Vite + Tailwind + PixiJS or Konva "
                 "(map) + Recharts (charts)",
        "weeks": [
            "W1  Static shell, routing, theme, mock-data map with 5 robots",
            "W2  Live WebSocket wiring, real robot movement on canvas, Fleet Overview",
            "W3  Decision Inspector + Incident Center on real coordination data",
            "W4  Benchmark Center + Replay scrubber",
            "W5  50-robot performance pass, polish, demo rehearsal",
        ],
        "qa": [
            ("How do you render 50+ robots at 30 fps without React re-rendering "
             "everything?",
             "High-frequency map state never enters React state. The socket writes "
             "into a mutable ref and the canvas renders from a requestAnimationFrame "
             "loop. Only low-frequency aggregates (KPIs, incident counts) are React "
             "state."),
            ("Is the Decision Inspector generated text?",
             "No. It renders the actual UtilityBreakdown numbers computed by the "
             "coordination engine - six weighted components and their sum. No LLM, "
             "no prose generation."),
            ("What happens to the UI if the backend dies mid-demo?",
             "The socket layer detects disconnect, the UI switches to a DEGRADED "
             "banner and keeps showing last-known state instead of blanking. This "
             "mirrors the system's own degraded-mode story."),
            ("Why dark theme?",
             "It is an industrial command-centre convention - reduces eye strain in "
             "control rooms and makes semantic state colours (green/amber/red) read "
             "clearly. It is a functional choice, not decoration."),
            ("How does a judge verify zero collisions?",
             "The Fleet Overview carries a live collision counter fed from the "
             "simulator's own collision check, and the Replay screen lets you "
             "re-examine any moment of the run."),
        ],
    },
    {
        "id": "M2", "role": "Backend / Integration Owner",
        "mission": "Own the FastAPI service AND the integration seam: one command "
                   "must boot the entire demo.",
        "features": [
            "FastAPI service: REST + WebSocket, OpenAPI schema as the contract",
            "WebSocket fleet telemetry fan-out at ~10 Hz",
            "Task / fleet management API (create, assign, track, complete)",
            "Simulation control API: start / pause / step / seed / scenario",
            "Fault injection API: kill robot, block aisle, drop packets, kill RMS",
            "Benchmark orchestration: run baseline + SWARMOS, return comparison",
            "INTEGRATION OWNER: docker-compose, single-command boot, smoke test",
            "OWNER of docs/INTEGRATION_CONTRACTS.md",
        ],
        "files": [
            "app/api/main.py              (FastAPI app factory)",
            "app/api/routes/*.py          (robots, tasks, sim, benchmark, replay)",
            "app/api/ws.py                (fleet snapshot broadcaster)",
            "app/api/schemas.py           (pydantic request/response models)",
            "app/orchestrator.py          (drives sim + coordination + persistence)",
            "docker-compose.yml, Makefile, scripts/smoke_test.sh",
        ],
        "consumes": "AMRState + tick events from M5; decisions/conflicts from M4; "
                    "KPIs and replay frames from M6; advisories from M3.",
        "produces": "Fleet snapshot (WebSocket), REST API for everything, event "
                    "stream into M6's store.",
        "stack": "Python 3.11 + FastAPI + Uvicorn + Pydantic v2 (already in "
                 "pyproject.toml). Docker Compose for the demo.",
        "weeks": [
            "W1  App skeleton, /health, robot list from a stub sim, OpenAPI live",
            "W2  Real orchestrator loop: sim tick -> coordination -> snapshot -> WS",
            "W3  Task API + simulation control + fault injection endpoints",
            "W4  Benchmark orchestration endpoint + replay endpoints",
            "W5  docker-compose one-command boot, smoke test, hardening",
        ],
        "qa": [
            ("You call this decentralized, but you have a central FastAPI server. "
             "Explain.",
             "The architecture is deliberately hybrid. FastAPI serves orchestration, "
             "monitoring and analytics. Time-critical collision avoidance runs in the "
             "coordination engine instances, which do not require the server. We "
             "demonstrate this by killing the RMS mid-run while the fleet keeps "
             "coordinating."),
            ("How do six modules stay compatible?",
             "One document, docs/INTEGRATION_CONTRACTS.md, defines every interface, "
             "plus the FastAPI OpenAPI schema is generated from Pydantic models so "
             "the frontend types cannot drift silently."),
            ("How do you push 50 robots at 10 Hz without saturating the socket?",
             "The snapshot is diff-friendly and capped: full state on connect, then "
             "per-tick payloads. If a client lags we drop intermediate frames rather "
             "than queue them - freshness beats completeness for a live map."),
            ("What is your single point of failure?",
             "The orchestrator process, for the dashboard path only. Coordination "
             "decisions are computed by the engine instances. We state this limit "
             "openly rather than claiming full decentralisation."),
            ("How long does it take to start your whole system from scratch?",
             "One command: docker-compose up. There is a smoke test that boots it, "
             "runs 3 robots for 30 ticks and asserts zero collisions."),
        ],
    },
    {
        "id": "M3", "role": "AI / ML",
        "mission": "Provide predictive intelligence that is trained on our own "
                   "simulation data, is measurable, and is advisory - never "
                   "safety-critical.",
        "features": [
            "Dataset generated from OUR simulator (no external dataset needed)",
            "Feature engineering: local robot density, reservation pressure,",
            "  battery, deadline slack, corridor congestion, historical wait",
            "Action classifier: MOVE / WAIT / REROUTE / CHARGE with confidence",
            "N4 PREDICTIVE CONGESTION FIELD - predict cell occupancy at t+delta",
            "  and feed it to the planner as edge-cost multipliers",
            "Model card: accuracy, confusion matrix, feature importance, limits",
            "Utility weight sensitivity study (answers 'why 0.30?')",
            "A/B harness: reactive coordination vs congestion-aware routing",
        ],
        "files": [
            "ml/dataset/build_dataset.py     (simulator logs -> training table)",
            "ml/features.py                  (feature extraction, shared at infer)",
            "ml/train_action_model.py        (train + evaluate + save)",
            "ml/congestion_field.py          (EWMA baseline, then learned model)",
            "ml/serve.py                     (load model, MLAdvice at inference)",
            "ml/model_card.md                (honest metrics and limitations)",
        ],
        "consumes": "Event log / dataset export from M6; live AMRState + "
                    "reservation pressure from M4 at inference time.",
        "produces": "MLAdvice (advisory action + confidence + features_used) to "
                    "M4; CongestionField (cost multipliers) to M5's planner.",
        "stack": "Python 3.11 + scikit-learn (GradientBoosting / RandomForest) + "
                 "Pandas + NumPy. Start with EWMA, add the learned model after.",
        "weeks": [
            "W1  Define features; get the simulator emitting a labelled event log",
            "W2  EWMA congestion field working end-to-end into the planner",
            "W3  Train + evaluate the action classifier, write the model card",
            "W4  Learned congestion prediction; A/B measured against EWMA",
            "W5  Weight sensitivity study; Decision Inspector feature display",
        ],
        "qa": [
            ("Where is the AI, really? Is it decoration?",
             "Two concrete places. (1) A congestion predictor that changes planner "
             "edge costs, measurably reducing completion time in an A/B test with "
             "identical seeds. (2) An action classifier advising MOVE/WAIT/REROUTE/"
             "CHARGE. Both are trained on data our simulator generated, and both "
             "have reported metrics."),
            ("What if your model is wrong? Can it cause a collision?",
             "No, by construction. The model is advisory. Safety is enforced by the "
             "deterministic spatio-temporal reservation engine, which the model "
             "cannot override. A wrong prediction costs efficiency, never safety."),
            ("Why not deep learning / reinforcement learning?",
             "Our dataset is tabular and modest, so gradient boosting is the "
             "appropriate choice and is interpretable via feature importance. RL "
             "would not converge in the available time and could not be safety-"
             "argued. We chose the honest tool, not the impressive-sounding one."),
            ("Where did your training data come from?",
             "Our own seeded simulator. Every run is reproducible from its seed, so "
             "the dataset is regenerable and auditable - which is stronger than an "
             "unrelated downloaded dataset."),
            ("Why are the utility weights 0.30 / 0.25 / 0.15 / 0.15 / 0.10 / 0.05?",
             "They started as engineering defaults. We then ran a sensitivity sweep "
             "over many weight vectors on identical scenarios and report the region "
             "where outcomes are stable. So the numbers are empirically supported, "
             "not asserted."),
        ],
    },
    {
        "id": "M4", "role": "Robotics / Multi-Agent Coordination (Adithya)",
        "mission": "Make many robots share contested space safely and efficiently "
                   "without a central brain making every movement decision.",
        "features": [
            "DONE Steps 1-4A: contracts, peer/intent registries, conflict",
            "  detection, spatio-temporal reservations, auction core - 296 tests",
            "Step 4B: distributed runtime bid exchange over a real transport",
            "  with timeouts, quorum, late bids, re-auction, TTL cleanup",
            "Deadlock detection (distributed wait-for graph + cycle detection)",
            "Deadlock recovery with aging-based anti-starvation guarantee",
            "Heartbeat failure detection + reservation invalidation",
            "WAIT / YIELD / SLOW / REROUTE policy (currently PROCEED/WAIT/YIELD)",
            "N1 VERIFIABLE BIDS - detect a robot lying about its own state",
            "N3 TAMPER-EVIDENT DECISION CHAIN - hash-linked audit trail",
            "N5 Degraded-mode ladder: FULL_MESH / LOCAL / CONSERVATIVE / SAFE_HALT",
            "Spatial broad phase to fix O(N^2) conflict detection",
            "Fault injection: loss, delay, duplication, partition, robot death",
        ],
        "files": [
            "app/coordination/auction.py         1003 lines  (Step 4A, DONE)",
            "app/coordination/reservation.py      949 lines  (Step 3, DONE)",
            "app/coordination/conflict.py         436 lines  (Step 2, DONE)",
            "app/coordination/models.py           207 lines  (Step 1, DONE)",
            "app/coordination/messages.py         189 lines  (Step 1, DONE)",
            "app/coordination/peer_registry.py    162 lines  (DONE)",
            "app/coordination/intent_registry.py  124 lines  (DONE)",
            "app/coordination/transport.py         81 lines  (Protocol only)",
            "NEW 4B: auction_runtime.py, inmemory_transport.py, dedup.py,",
            "        auction_messages.py, deadlock.py, heartbeat.py",
        ],
        "consumes": "AMRState + MovementIntent from M5; MLAdvice from M3.",
        "produces": "ConflictResult, AuctionDecision (with UtilityBreakdown), "
                    "reservation state, CoordinationDirective to M5, "
                    "RerouteRequest to M5's planner, events to M6.",
        "stack": "Python 3.11 + Pydantic v2 + pytest. No networking deps in the "
                 "core - transport is injected via a Protocol.",
        "weeks": [
            "W1  Step 4B: transport, dedup, runtime loop, timeouts, TTL, re-auction",
            "W2  3-robot vertical slice with M5; spatial broad phase",
            "W3  Deadlock detection + recovery; heartbeat + reservation invalidation",
            "W4  N1 verifiable bids; SLOW/REROUTE policy; degraded-mode ladder",
            "W5  N3 decision chain; fault-injection scenarios; 50-robot scale test",
        ],
        "qa": [
            ("This runs in one process. In what sense is it decentralized?",
             "The winner-selection function compute_ranking is pure and has no "
             "shared state. We run N independent engine instances, partition the "
             "message bus so they cannot talk, and show every instance "
             "independently computes the identical decision_id. That is the "
             "convergence property, demonstrated rather than asserted."),
            ("How do you guarantee zero collisions?",
             "We do not claim a formal guarantee - that would need proof we have "
             "not done. We claim zero collisions in all tested scenarios, enforced "
             "by a reservation engine that is the single authority for entering a "
             "contested corridor, plus a SAFE_HALT fallback when a robot cannot "
             "confirm a reservation."),
            ("What stops the same robot losing every auction forever?",
             "An exponential aging term: aging = 1 - exp(-t*ln2/half_life), "
             "half_life 60 s. It is bounded, monotonic and weighted at 0.15, so a "
             "repeatedly-losing robot's utility rises until it wins. Aging is also "
             "the second tie-break key."),
            ("Why an auction instead of fixed priorities or a central planner?",
             "Fixed priorities starve low-priority robots and ignore context. A "
             "central planner reintroduces the latency and single-point-of-failure "
             "the problem statement asks us to avoid. An auction uses local "
             "information only, and determinism gives us reproducibility without a "
             "central auctioneer."),
            ("What if a robot lies about its battery to win?",
             "We cross-check every declared bid value against independently "
             "observed peer state. Inconsistent bids are rejected and lower the "
             "robot's trust score. We demo this live by making a robot lie."),
            ("What are the known limits of your design?",
             "Reservation authority is currently a shared instance, which is a "
             "hidden centralised component. Utility weights are empirically tuned, "
             "not optimal. We have no formal deadlock-freedom proof. We state all "
             "three openly."),
        ],
    },
    {
        "id": "M5", "role": "Simulation + Path Planning",
        "mission": "Own the virtual warehouse, robot motion, AND path planning - "
                   "plus the stop-and-wait baseline we are measured against.",
        "features": [
            "Warehouse world: grid, racks, aisles, pick stations, charger bays",
            "Robot kinematics for 50 robots (100+ for stress tests)",
            "A* path planning + D* Lite style replanning on blockage",
            "Congestion-aware costs from M3's CongestionField",
            "Scenario scripting: congestion, blocked aisle, robot failure, comms",
            "SEEDED DETERMINISM - same seed reproduces the run exactly",
            "Collision detection (ground truth for the zero-collision claim)",
            "STOP-AND-WAIT BASELINE POLICY - what the 20% is measured against",
            "Tick loop driving the whole simulation",
        ],
        "files": [
            "sim/world.py            (grid, racks, aisles, chargers)",
            "sim/robot.py            (kinematics, battery drain, status FSM)",
            "sim/engine.py           (tick loop, seeded RNG, collision check)",
            "sim/scenarios.py        (named reproducible scenarios)",
            "planner/astar.py        (A* on the warehouse grid)",
            "planner/replan.py       (D* Lite style incremental replanning)",
            "planner/baseline.py     (STOP_AND_WAIT policy)",
        ],
        "consumes": "CoordinationDirective + RerouteRequest from M4; "
                    "CongestionField from M3; scenario commands from M2.",
        "produces": "AMRState per robot per tick; MovementIntent with a strictly "
                    "increasing path_version on every replan; collision and task "
                    "completion events.",
        "stack": "Python 3.11 + NumPy. Deterministic seeded RNG only - no "
                 "unseeded randomness anywhere.",
        "weeks": [
            "W1  Grid world + 3 robots moving + A* + seeded tick loop",
            "W2  Integrate with M4 coordination: directives actually change motion",
            "W3  Replanning, blocked aisle, robot failure, charger bays",
            "W4  STOP_AND_WAIT baseline policy + scenario library",
            "W5  Scale to 50, then 100-robot stress test, performance profiling",
        ],
        "qa": [
            ("Is your simulation physically realistic?",
             "It is a kinematic simulation with velocity limits and battery drain, "
             "not a dynamics or sensor simulation. We state that clearly. It is "
             "sufficient and appropriate for evaluating coordination behaviour, "
             "which is what the problem statement targets."),
            ("Why A* and not RRT or a learned planner?",
             "The warehouse is a static discrete grid, where A* is optimal and fast "
             "with an admissible heuristic. RRT targets continuous high-dimensional "
             "spaces we do not have. For replanning we use a D* Lite style "
             "incremental update to avoid full recomputation."),
            ("How is path_version handled?",
             "Every replan strictly increments it. This is what lets coordination "
             "reject stale bids and stale intents. It is enforced in the planner, "
             "not left to callers."),
            ("Is the stop-and-wait baseline a fair comparison?",
             "Yes - identical map, identical seed, identical task stream, identical "
             "robot count, identical kinematics. The ONLY difference is the "
             "coordination policy. Anything else would invalidate the comparison."),
            ("Can you reproduce a specific run a judge saw?",
             "Yes. Every run is fully determined by its seed and scenario ID. Same "
             "seed, same run, every time - which is also how we generate the ML "
             "training data."),
        ],
    },
    {
        "id": "M6", "role": "Database / Analytics + Benchmark",
        "mission": "Own the evidence. Store every event, compute every metric, and "
                   "produce the headline number the whole submission rests on.",
        "features": [
            "Schema: robots, tasks, events, decisions, conflicts, reservations",
            "Event store with run_id + tick ordering (enables replay)",
            "BENCHMARK HARNESS - the single most important deliverable:",
            "  run STOP_AND_WAIT and SWARMOS on identical seeds, compare",
            "All 10 metrics: completion time, collisions, deadlocks, throughput,",
            "  avg wait, reroutes, distance, congestion, recovery time, comms",
            "KPI aggregation for the dashboard",
            "Replay frame API (reconstruct any tick of any run)",
            "Dataset export for M3's training",
            "Reproducibility: every reported number traceable to a run_id",
        ],
        "files": [
            "db/schema.sql            (tables + indexes)",
            "db/store.py              (event write path, batched)",
            "db/queries.py            (KPI + replay queries)",
            "benchmark/harness.py     (run pairs of policies over seed sets)",
            "benchmark/metrics.py     (the 10 metric computations)",
            "benchmark/report.py      (comparison table + chart data)",
        ],
        "consumes": "Event log from M4 and M5 via M2's orchestrator.",
        "produces": "KPIs and benchmark comparison for M1 via M2; replay frames; "
                    "training dataset for M3.",
        "stack": "SQLite for the demo (zero setup, file-based, replayable), with "
                 "a Postgres-compatible schema. Pandas for aggregation.",
        "weeks": [
            "W1  Schema + event write path + basic queries",
            "W2  KPI aggregation feeding the dashboard",
            "W3  BENCHMARK HARNESS producing the first real comparison number",
            "W4  All 10 metrics + replay frame reconstruction",
            "W5  Multi-seed statistical runs (mean + spread, not one lucky run)",
        ],
        "qa": [
            ("Where does the 20% improvement number come from?",
             "From benchmark/harness.py at runtime. It runs both policies over "
             "identical seeds and computes the delta in total completion time. It "
             "is never hard-coded. We report the seed set and the spread, not a "
             "single best run."),
            ("How do we know you did not pick a favourable seed?",
             "We run a set of seeds and report mean and spread. Every number is "
             "traceable to a run_id in the database, and any run can be replayed."),
            ("Why SQLite and not something bigger?",
             "The demo must boot with zero setup and be replayable from a single "
             "file. The schema is Postgres-compatible, so scaling is a "
             "configuration change, not a redesign. Choosing the smallest thing "
             "that works is an engineering decision."),
            ("Can you prove zero collisions rather than assert it?",
             "The simulator performs an independent geometric collision check every "
             "tick and writes a COLLISION event. Zero collisions means zero such "
             "rows, and that query is run live in the demo."),
            ("What is the write load at 50 robots?",
             "Events are batched per tick rather than written individually, and the "
             "event table is indexed on (run_id, tick). Persistence is off the "
             "simulation's critical path."),
        ],
    },
]


def build(out_path: str) -> str:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # ---------------------------------------------------------- 1 title
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    tf = _txbox(s, Inches(0.9), Inches(1.9), Inches(11.5), Inches(3.4))
    _set(tf.paragraphs[0], "SWARMOS", size=66, bold=True, space_after=4)
    _set(tf.add_paragraph(),
         "Edge-AI Based Distributed Fleet Coordination for "
         "Autonomous Mobile Robots in Smart Warehouses",
         size=19, color=ACCENT, space_after=14)
    _set(tf.add_paragraph(),
         "SIH26123  |  Bharat Electronics Limited  |  Robotics and Drones",
         size=14, color=MUTED, space_after=6)
    _set(tf.add_paragraph(),
         "6-Member Team Plan  |  v1 - for team review",
         size=14, color=MUTED)
    note(s, "Read this, then send me your Section-by-Section status using "
            "docs/TEAM_MEMBER_STATUS_PROMPT.md", y=6.5, color=ACCENT)

    # ---------------------------------------------------------- 2 problem
    s = new_slide(prs, "The Problem",
                  "Why today's warehouse fleets are fragile")
    bullets(s, [
        "Modern warehouses run dozens of Autonomous Mobile Robots in shared aisles",
        "The usual approach is cloud-centric central planning. Three failure modes:",
        ("Latency - every movement decision makes a network round trip", 1),
        ("Wi-Fi dead zones - a robot that cannot reach the server cannot act", 1),
        ("Single point of failure - the server dies, the fleet freezes", 1),
        "",
        "What the problem statement demands:",
        ("At least 3 AMRs, decentralized inter-robot messaging", 1),
        ("Dynamic conflict AND deadlock resolution", 1),
        ("Task allocation and rerouting, multi-agent path planning", 1),
        ("Multi-robot simulation and a fleet dashboard", 1),
    ], size=15)
    note(s, "Our answer: decide locally, coordinate peer-to-peer, keep the "
            "central server for orchestration and analytics only.")

    # ---------------------------------------------------------- 3 the 2 numbers
    s = new_slide(prs, "The Only Two Numbers We Are Judged On",
                  "Every task in this plan maps back to one of these", accent=OK)
    kpi_cards(s, [
        ("0", "inter-robot collisions in all tested scenarios", OK),
        (">= 20%", "reduction in total task completion time vs stop-and-wait", ACCENT),
    ], y=1.55, h=1.9)
    bullets(s, [
        "Both must come from the real benchmark engine. Never hard-coded.",
        "A measured 14% beats a fabricated 22%, because a fabricated number dies "
        "in the Q&A round.",
        "",
        "This is why the BENCHMARK HARNESS (M6) is the highest-priority item in "
        "the entire project - it is the only thing that can produce the number.",
        "And it is why the 3-ROBOT VERTICAL SLICE comes before any novelty work:",
        ("nothing can be measured until robots actually move end to end.", 1),
    ], y=3.8, size=14)

    # ---------------------------------------------------------- 4 vision
    s = new_slide(prs, "What SWARMOS Is",
                  "A distributed fleet operating system, not a robot simulator")
    bullets(s, [
        "The simulation represents the physical world. It is not the product.",
        "The coordination intelligence IS the product.",
        "The web application is the operational control centre.",
        "",
        "Core capabilities:",
        ("Decentralized peer coordination and local decision making", 1),
        ("Spatio-temporal conflict detection - predict conflicts before overlap", 1),
        ("Spatio-temporal corridor reservations - book space AND time", 1),
        ("Decentralized auction / negotiation for contested space", 1),
        ("Deadlock detection and recovery, heartbeat failure detection", 1),
        ("Battery-aware decisions, congestion and blocked-aisle recovery", 1),
        ("Decision explainability, replay, analytics and benchmarking", 1),
        "",
        "Demo target: 50 AMRs, with 100+ stress testing where practical.",
        ("Fleet size alone is not the innovation. Measured scalable behaviour is.", 1),
    ], size=14, gap=4)

    # ---------------------------------------------------------- 5 architecture
    s = new_slide(prs, "System Architecture",
                  "Hybrid by design - central for orchestration, edge for safety")
    y0 = 1.45
    c = _rect(s, Inches(3.9), Inches(y0), Inches(5.5), Inches(0.85),
              PANEL, line=MUTED)
    _set(c.text_frame.paragraphs[0],
         "CENTRAL WMS / CLOUD\nHigh-level orders, analytics, dashboard",
         size=12, color=MUTED)
    c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    c = _rect(s, Inches(2.6), Inches(y0 + 1.15), Inches(8.1), Inches(0.85),
              PANEL, line=ACCENT)
    _set(c.text_frame.paragraphs[0],
         "EDGE MESH / COORDINATION NETWORK\n"
         "peer state, path intent, conflicts, auctions, reservations",
         size=12, color=ACCENT)
    c.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    for i in range(5):
        x = 1.15 + i * 2.25
        lbl = "AMR N" if i == 4 else f"AMR {i+1}"
        cc = _rect(s, Inches(x), Inches(y0 + 2.3), Inches(1.95), Inches(1.25),
                   PANEL, line=OK)
        _set(cc.text_frame.paragraphs[0],
             f"{lbl}\nlocal agent\nlocal plan\nlocal coord", size=10, color=FG)
        cc.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    bullets(s, [
        "Movement decisions do NOT round-trip through the central server.",
        "If the central RMS dies: local collision avoidance, conflict resolution, "
        "rerouting and failure detection continue. Dashboard and analytics degrade.",
        "We will not claim the central server is irrelevant - it matters for "
        "orchestration. We claim the fleet does not freeze without it.",
    ], y=5.35, size=13)

    # ---------------------------------------------------------- 6 module map
    s = new_slide(prs, "The Six Modules", "Who owns what, and where they meet")
    table(s, ["", "Member", "Owns", "Key output consumed by others"], [
        ["M1", "Frontend / UI-UX", "12 screens, canvas map, Decision Inspector",
         "the demo itself"],
        ["M2", "Backend / INTEGRATION", "FastAPI, WebSocket, docker-compose, contracts",
         "fleet snapshot -> M1"],
        ["M3", "AI / ML", "dataset, action model, congestion prediction",
         "MLAdvice -> M4, CongestionField -> M5"],
        ["M4", "Robotics / Multi-Agent", "conflicts, reservations, auctions, deadlock",
         "AuctionDecision, directives -> M5"],
        ["M5", "Simulation + PLANNING", "warehouse, 50 robots, A*, baseline policy",
         "AMRState + MovementIntent -> M4"],
        ["M6", "Database / Analytics", "event store, BENCHMARK HARNESS, KPIs",
         "the headline 20% number"],
    ], y=1.4, size=11, col_widths=[0.5, 2.4, 5.0, 4.3])
    bullets(s, [
        "Two changes from the original split, both deliberate:",
        ("A* PATH PLANNING moved to M5 - the planner needs the warehouse grid "
         "that M5 already owns. Without a planner there are no paths, so no "
         "conflicts, so nothing to coordinate.", 1),
        ("M2 is also INTEGRATION OWNER - six modules that have never run "
         "together is the classic way hackathon teams fail. Someone must own "
         "the seam, and the API layer is where everything physically meets.", 1),
    ], y=4.35, size=13)

    # ---------------------------------------------------------- 7 status
    s = new_slide(prs, "Honest Starting Position",
                  "M4 coordination core is already built, audited and tested",
                  accent=OK)
    kpi_cards(s, [
        ("296", "tests passing, verified 2026-09-20", OK),
        ("~3.1k", "lines of production coordination code", ACCENT),
        ("4A", "phases complete (1, 2, 3, 4A)", VIOLET),
        ("0", "critical or high audit findings", OK),
    ], y=1.5, h=1.45)
    table(s, ["Module", "Lines", "Status"], [
        ["auction.py - decentralized auction core", "1003", "COMPLETE + AUDITED"],
        ["reservation.py - spatio-temporal reservations", "949", "COMPLETE"],
        ["conflict.py - spatio-temporal conflict detection", "436", "COMPLETE"],
        ["models.py / messages.py - contracts", "396", "COMPLETE"],
        ["peer_registry.py / intent_registry.py", "286", "COMPLETE"],
        ["transport.py - Protocol only, no implementation", "81", "STEP 4B"],
        ["distributed runtime, deadlock, heartbeat, benchmark", "-", "NOT STARTED"],
    ], y=3.3, size=11, col_widths=[6.4, 1.6, 4.2])
    note(s, "This is the real baseline. Everything marked NOT STARTED is "
            "genuinely not started - no invented progress.", y=6.55)

    # ---------------------------------------------------------- 8 phases
    s = new_slide(prs, "Four Phases", "Ordered to kill risk early, not late")
    table(s, ["Phase", "Goal", "Definition of done", "Why this order"], [
        ["1", "Skeleton that MOVES",
         "3 robots, real A*, real conflicts, real auctions, ugly UI, one command boots it",
         "Integration risk dies on day 1, not day 30"],
        ["2", "MEASUREMENT",
         "Benchmark harness + stop-and-wait baseline + event store = a REAL number",
         "Both SIH success criteria need this. No number, no score"],
        ["3", "Scale + intelligence",
         "50 robots, spatial broad phase, ML model, deadlock detection, failure recovery",
         "Now improvements can be measured against Phase 2"],
        ["4", "Novelty + polish",
         "N1/N2/N3, fault injection, beautiful dashboard, demo rehearsal, Q&A drills",
         "Novelty on a measured system wins. On an unmeasured one it loses"],
    ], y=1.45, size=11, col_widths=[0.7, 2.3, 5.2, 4.0])
    note(s, "HARD RULE: no novelty features until Phase 2 produces a real "
            "measured number. This is the single most important scheduling "
            "decision in the plan.", y=5.6, color=BAD)

    # ---------------------------------------------------- 9..32 per member
    for m in MEMBERS:
        col = MEMBER_COLORS[m["id"]]

        # (a) mission + features
        s = new_slide(prs, f"{m['id']} - {m['role']}",
                      "Your mission and the features you own", accent=col)
        sh = _rect(s, Inches(0.55), Inches(1.3), Inches(12.2), Inches(0.8),
                   PANEL, line=col)
        tf = sh.text_frame
        tf.margin_left = Inches(0.18)
        tf.margin_top = Inches(0.1)
        _set(tf.paragraphs[0], m["mission"], size=14, color=FG, bold=True)
        bullets(s, [(f, 1 if f.startswith("  ") else 0) for f in m["features"]],
                y=2.35, size=14, gap=5)

        # (b) files + interfaces
        s = new_slide(prs, f"{m['id']} - Files and Interfaces",
                      "What you own on disk, and who you depend on", accent=col)
        tfx = _txbox(s, Inches(0.55), Inches(1.3), Inches(12.2), Inches(2.5))
        _set(tfx.paragraphs[0], "FILES YOU OWN", size=13, color=col, bold=True)
        for f in m["files"]:
            _set(tfx.add_paragraph(), f, size=11, color=FG, font="Consolas",
                 space_after=2)
        bullets(s, [
            "YOU CONSUME (inputs from others)",
            (m["consumes"], 1),
            "",
            "YOU PRODUCE (outputs others depend on)",
            (m["produces"], 1),
            "",
            "STACK",
            (m["stack"], 1),
        ], y=4.0, size=13, gap=4)
        note(s, "All contracts are defined in docs/INTEGRATION_CONTRACTS.md. "
                "Change that file first, then your code.", y=6.6, color=col)

        # (c) weekly deliverables
        s = new_slide(prs, f"{m['id']} - Week by Week",
                      "Every week ends with something demo-visible", accent=col)
        table(s, ["Week", "Deliverable"],
              [[w.split("  ", 1)[0], w.split("  ", 1)[1]] for w in m["weeks"]],
              y=1.5, size=13, col_widths=[1.0, 11.2])
        bullets(s, [
            "Rules that apply to everyone:",
            ("Nothing is 'done' until it runs in the integrated demo.", 1),
            ("Commit small and often. Never break main.", 1),
            ("If you are blocked for more than half a day, say so immediately.", 1),
            ("No secrets in code, docs, commits or screenshots. Ever.", 1),
        ], y=4.3, size=13)

        # (d) Q&A defence
        s = new_slide(prs, f"{m['id']} - Your Q&A Defence",
                      "SIH judges question members individually. Know these cold.",
                      accent=col)
        items = []
        for q, a in m["qa"]:
            items.append((f"Q: {q}", 0, col))
            items.append((f"A: {a}", 1))
        bullets(s, items, y=1.3, size=12, gap=7, h=5.9)

    # ---------------------------------------------------------- 33 novelty
    s = new_slide(prs, "Four Novelty Features",
                  "One coherent story, told four ways", accent=VIOLET)
    table(s, ["", "Feature", "Owner", "The 30-second stage moment"], [
        ["N1", "Verifiable bids / anti-cheat coordination", "M4",
         "'I'll make R17 lie about its battery' - it is flagged, loses, fleet runs on"],
        ["N2", "Counterfactual Decision Inspector", "M1 + M4",
         "'R12 lost by 0.03 - it would have won with 14s more waiting time'"],
        ["N3", "Tamper-evident decision chain", "M4 + M6",
         "Re-run the seed: identical hash. Corrupt one record: verification points at it"],
        ["N4", "Predictive congestion field", "M3 + M5",
         "A/B same seed: congestion-aware routing measurably finishes faster"],
    ], y=1.45, size=11, col_widths=[0.5, 3.6, 1.2, 6.9])
    bullets(s, [
        "The narrative that ties them together:",
        ("SWARMOS makes coordination decisions that are PREDICTIVE (N4), "
         "EXPLAINABLE (N2), VERIFIABLE even when a robot lies (N1), and "
         "REPRODUCIBLE and AUDITABLE after the fact (N3).", 1, VIOLET),
        "",
        "Why these four: each builds on determinism and explainability work that "
        "is ALREADY DONE - cheap for us, expensive for anyone else to copy. None "
        "requires a new technology, so we stay clear of technology soup.",
        "",
        "Deliberately NOT doing: blockchain buzzwords, RL for yield policy, forced "
        "ROS2/Zenoh, deep learning for appearance, formal certification claims.",
    ], y=3.7, size=13)

    # ---------------------------------------------------------- 34 demo script
    s = new_slide(prs, "The 8-Minute Demo Script",
                  "Rehearsed, timed, with a fallback", accent=OK)
    table(s, ["Min", "What the judge sees", "Driver"], [
        ["0:00", "50 AMRs operating normally on the command centre map", "M1"],
        ["1:00", "Create overlapping-path congestion; future conflicts light up", "M1"],
        ["2:00", "Open the auction: utility breakdown, winner, reservation", "M4"],
        ["3:00", "Winner proceeds, loser waits/yields/reroutes - live on the map", "M4"],
        ["3:45", "Decision Inspector counterfactual: why R12 lost, by how much", "M1"],
        ["4:30", "Block an aisle: affected robots invalidate paths and reroute", "M5"],
        ["5:15", "Kill R27: heartbeat timeout, reservations invalidated, task recovered", "M4"],
        ["6:00", "Make a robot LIE about its battery: bid rejected, trust drops", "M4"],
        ["6:45", "Kill the central RMS: local coordination continues", "M2"],
        ["7:15", "Benchmark Center: measured comparison vs stop-and-wait", "M6"],
        ["7:45", "Replay the same seed: identical decision hash", "M6"],
    ], y=1.4, size=11, col_widths=[0.9, 9.3, 2.0])
    note(s, "FALLBACK, non-negotiable: a pre-recorded video AND a seeded replay "
            "file on a USB stick. Venue Wi-Fi and live demos fail. Never present "
            "without a fallback.", y=6.1, color=BAD)

    # ---------------------------------------------------------- 35 charter
    s = new_slide(prs, "Engineering Charter",
                  "The rules we hold each other to", accent=BAD)
    bullets(s, [
        "NO fake AI, fake metrics, fake distributed behaviour or decorative features.",
        "NO hard-coded benchmark results. The number comes from the harness or it "
        "does not exist.",
        "NO unsupported claims: no formal safety certification, no proven "
        "optimality, no guaranteed deadlock freedom. We say 'in all tested "
        "scenarios'.",
        "NO secrets in source, docs, commits, logs or screenshots.",
        "NO giant files without a strong reason. No technology soup.",
        "Do not randomly rewrite another member's working module.",
        "Do not break a contract without a migration note and updated tests.",
        "Run the tests after every change. Inspect the diff before committing.",
        "",
        "Acknowledged limitations we will state OPENLY to judges:",
        ("Reservation authority is currently a shared instance - a hidden "
         "centralised component.", 1, WARN),
        ("Utility weights are empirically tuned, not proven optimal.", 1, WARN),
        ("Simulation is kinematic, not full dynamics or sensor simulation.", 1, WARN),
        ("No formal deadlock-freedom proof.", 1, WARN),
    ], size=13, gap=5)
    note(s, "Judges reward acknowledged limitations. They punish limitations they "
            "discover themselves.", y=6.65, color=OK)

    # ---------------------------------------------------------- 36 next steps
    s = new_slide(prs, "What I Need From You This Week",
                  "Then we lock the architecture and build", accent=ACCENT)
    bullets(s, [
        "1. Read this deck and push back hard. If your section is wrong, say so.",
        "2. Send me your status document using the prompt in "
        "docs/TEAM_MEMBER_STATUS_PROMPT.md",
        ("Be honest about what is NOT built. Guessing is worse than 'not started'.", 1),
        ("Section 5 (data contracts) matters most - it is where integration "
         "breaks.", 1),
        ("Do NOT paste any tokens, keys or passwords into the output.", 1),
        "3. First team call agenda - we must decide these together:",
        ("Coordinate system: continuous metres vs grid cells, and who converts", 1),
        ("Robot ID and task ID naming format", 1),
        ("Who is authoritative for robot state (proposal: M5's simulator)", 1),
        ("Tick rate, and who drives the loop", 1),
        ("Confirmation that ML is ADVISORY, never in the safety path", 1),
        "4. Then: I finish Step 4B, M5 gets 3 robots moving, and we do the "
        "vertical slice together.",
    ], size=14, gap=6)
    note(s, "Deck version v1. It becomes v2 once your real status documents are "
            "in - this version contains my assumptions about your modules.",
         y=6.6, color=ACCENT)

    prs.save(out_path)
    return out_path


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(here), "SWARMOS_Team_Plan_SIH26123.pptx")
    path = build(out)
    p = Presentation(path)
    print("Wrote: %s" % path)
    print("Slides: %d" % len(p.slides.__iter__.__self__._sldIdLst))

# File contains AI-generated response based on internal company sources
