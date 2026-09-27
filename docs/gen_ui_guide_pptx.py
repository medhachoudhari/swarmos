#!/usr/bin/env python3
"""
Generate SWARMOS_UI_UX_Guide_SIH26123.pptx -- the operator / judge guide to the
ROBONEX SWARMOS web UI.

This is the "how do I read this screen" deck. It documents every page, region,
control, metric, colour and keyboard shortcut in web/, so a person who has
never seen the console can sit down and drive it.

Every label, id, default value and string in this deck was read out of the
actual source (web/landing.html, web/index.html, web/js/*, web/styles/*),
not invented. If the UI changes, re-read the source and regenerate.

Theme helpers are imported from gen_team_plan_pptx.py so this deck matches the
house style of the other two decks.

Usage:
    /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 docs/gen_ui_guide_pptx.py

Output:
    SWARMOS_UI_UX_Guide_SIH26123.pptx  (repo root)
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from pptx import Presentation
from pptx.util import Inches, Pt

from gen_team_plan_pptx import (
    ACCENT, BAD, BG, FG, MUTED, OK, PANEL, VIOLET, WARN,
    H, W,
    _rect, _set, _txbox,
    bullets, kpi_cards, new_slide, note, table,
)

TEAL = VIOLET.__class__(0x4F, 0xB3, 0xA6)     # --state-sovereign
PURPLE = VIOLET.__class__(0xA8, 0x55, 0xC4)   # --state-quarantined
OUT = "SWARMOS_UI_UX_Guide_SIH26123.pptx"


# ------------------------------------------------------------------ helpers

def title_slide(prs):
    """Cover slide. Deliberately quiet: wordmark, product, purpose."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG

    from pptx.enum.shapes import MSO_SHAPE
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                 Inches(0), Inches(0), Inches(0.14), H)
    bar.fill.solid()
    bar.fill.fore_color.rgb = TEAL
    bar.line.fill.background()
    bar.shadow.inherit = False

    tf = _txbox(slide, Inches(0.9), Inches(2.0), Inches(11.6), Inches(3.2))
    _set(tf.paragraphs[0], "ROBONEX", size=13, color=TEAL, bold=True,
         space_after=10)
    _set(tf.add_paragraph(), "SWARMOS UI / UX Guide", size=44, bold=True,
         space_after=8)
    _set(tf.add_paragraph(),
         "How to read the console: every screen, panel, control, colour and shortcut",
         size=17, color=MUTED, space_after=18)
    _set(tf.add_paragraph(),
         "SIH26123  -  Edge-AI Based Distributed Fleet Coordination for AMRs",
         size=12, color=MUTED, space_after=4)
    _set(tf.add_paragraph(),
         "Bharat Electronics Limited  -  Member 4, Coordination",
         size=12, color=MUTED)

    tf2 = _txbox(slide, Inches(0.9), Inches(6.4), Inches(11.6), Inches(0.6))
    _set(tf2.paragraphs[0],
         "Source of truth: web/landing.html, web/index.html, web/js/**, web/styles/tokens.css",
         size=10, color=MUTED)
    return slide


def two_col(slide, left_title, left_items, right_title, right_items,
            y=1.45, h=5.0, accent_l=ACCENT, accent_r=TEAL, size=12):
    """Two labelled panels side by side. Used for compare / contrast pages."""
    for i, (t, items, col) in enumerate((
            (left_title, left_items, accent_l),
            (right_title, right_items, accent_r))):
        x = 0.55 + i * 6.25
        sh = _rect(slide, Inches(x), Inches(y), Inches(5.95), Inches(h),
                   PANEL, line=col)
        tf = sh.text_frame
        tf.margin_left = Inches(0.18)
        tf.margin_right = Inches(0.14)
        tf.margin_top = Inches(0.14)
        _set(tf.paragraphs[0], t, size=14, color=col, bold=True, space_after=8)
        for it in items:
            lvl = 0
            if isinstance(it, tuple):
                it, lvl = it[0], it[1]
            _set(tf.add_paragraph(), it, size=size - lvl,
                 color=FG if lvl == 0 else MUTED, space_after=5)


def swatches(slide, rows, y=1.5, h=0.46, gap=0.1, x=0.55, w=12.2,
             label_size=12):
    """rows: list of (colour, name, meaning). A colour chip beside its meaning."""
    for i, (col, name, meaning) in enumerate(rows):
        yy = y + i * (h + gap)
        chip = _rect(slide, Inches(x), Inches(yy), Inches(0.42), Inches(h), col)
        chip.line.fill.background()
        tf = _txbox(slide, Inches(x + 0.58), Inches(yy - 0.02),
                    Inches(2.7), Inches(h))
        _set(tf.paragraphs[0], name, size=label_size, color=col, bold=True)
        tf2 = _txbox(slide, Inches(x + 3.35), Inches(yy - 0.02),
                     Inches(w - 3.5), Inches(h))
        _set(tf2.paragraphs[0], meaning, size=label_size, color=FG)


def steps(slide, items, y=1.45, x=0.55, w=12.2, size=12.5, gap=0.52):
    """Numbered walkthrough steps: (n, action, what to look at)."""
    for i, (action, watch) in enumerate(items):
        yy = y + i * gap
        num = _rect(slide, Inches(x), Inches(yy), Inches(0.42), Inches(0.42),
                    PANEL, line=ACCENT)
        ntf = num.text_frame
        ntf.margin_left = Inches(0.02)
        ntf.margin_top = Inches(0.02)
        p = ntf.paragraphs[0]
        _set(p, str(i + 1), size=13, color=ACCENT, bold=True)
        from pptx.enum.text import PP_ALIGN
        p.alignment = PP_ALIGN.CENTER

        tf = _txbox(slide, Inches(x + 0.58), Inches(yy - 0.04),
                    Inches(w - 0.6), Inches(0.5))
        _set(tf.paragraphs[0], action, size=size, color=FG, bold=True,
             space_after=1)
        _set(tf.add_paragraph(), watch, size=size - 1.5, color=MUTED)


# ================================================================== content

def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # ---------------------------------------------------------------- cover
    title_slide(prs)

    # ------------------------------------------------------- 1. what/where
    s = new_slide(prs, "What this deck is",
                  "Read it once before you touch the console, or use it as a reference at the keyboard",
                  accent=TEAL)
    bullets(s, [
        "THE PRODUCT HAS EXACTLY TWO SCREENS",
        ("Landing page  -  web/landing.html  -  the poster / entry screen. One button.", 1),
        ("Operator console  -  web/index.html  -  everything else. Map + 5 panels + telemetry.", 1),
        "",
        "HOW TO START IT",
        ("./run.sh --demo          starts the server, waits for /api/health, opens a browser,", 1),
        ("                         and starts the reference run so the map is already moving.", 1),
        ("./run.sh                 server only, on http://127.0.0.1:8770", 1),
        ("./run.sh 8080            a different port", 1),
        ("./run.sh --test          run the test suite instead of serving", 1),
        ("./run.sh --check         engine self-check (20 ticks + trace hash), then exit", 1),
        ("Remote host? ssh -L 8770:127.0.0.1:8770 <host> first, then open the URL locally.", 1),
        "",
        "THE READING RULE THAT EXPLAINS THE WHOLE UI",
        ("Every empty state names a CAUSE and an ACTION. If a panel is blank it tells you why", 1),
        ("it is blank and what to press. You are never expected to guess.", 1),
        ("A missing value always renders as  --  , never as 0. A zero on this screen is a real", 1),
        ("measured zero. \"A zero that means 'no data' is a lie the operator cannot detect.\"", 1),
    ], size=13.5, gap=3)
    note(s, "Dark theme only. There is no theme toggle, no login, no settings page. "
            "The console is the product.", y=6.62, color=MUTED)

    # ------------------------------------------------------- 2. landing map
    s = new_slide(prs, "Screen 1  -  ROBONEX landing page",
                  "web/landing.html  -  a single-viewport poster. It does not scroll.",
                  accent=TEAL)
    table(s,
          ["Region", "What it shows (exact text)", "Interactive?"],
          [
              ["Header left", "ROBONEX  (wordmark)", "No"],
              ["Header right", "SIH / SMART INDIA HACKATHON   -   SWARMOS", "No"],
              ["Hero", "ROBONEX  /  \"Distributed intelligence for autonomous warehouse fleets.\"\n"
                       "\"Every robot decides locally. The fleet stays coordinated.\"", "No"],
              ["Stage", "robot-hero.svg  -  an AMR mobile base, front three-quarter view", "No"],
              ["Capability card", "SWARMOS  /  DECENTRALIZED MULTI-AMR COORDINATION\n"
                                  "Decentralized coordination - Real-time conflict resolution -\n"
                                  "Dynamic task allocation - Spatio-temporal coordination -\n"
                                  "Failure recovery - Edge intelligence", "No"],
              ["About", "AUTONOMOUS - DISTRIBUTED - RESILIENT - MULTI-AMR", "No"],
              ["System status", "FLEET STATUS - <value>      AMR NETWORK - <value>\n"
                                "Live, polled from the server. Shows -- until it answers.", "No (live)"],
              ["Call to action", "ENTER SWARMOS  ->", "YES - the only control"],
          ],
          y=1.4, size=10.5, col_widths=[2.0, 7.4, 2.0])
    note(s, "There is NO nav bar, NO feature grid, NO stats counter, NO footer and NO scroll "
            "animation on this page. One button: ENTER SWARMOS (#lp-enter) -> the console.",
         y=6.58, color=TEAL)

    # ------------------------------------------- 3. landing status dots
    s = new_slide(prs, "Landing page  -  the two status rows",
                  "These are live probes, not decoration. Read them before you present.",
                  accent=TEAL)
    bullets(s, [
        "FLEET STATUS",
        ("Answers 'is a simulation running right now?'. Populated from the server's state.", 1),
        ("Shows  --  with an unknown dot before the first successful poll.", 1),
        "",
        "AMR NETWORK",
        ("Answers 'can this page reach the SWARMOS backend at all?'.", 1),
        ("If this stays down, the console will also be Offline - fix the server first.", 1),
        "",
        "ENTER SWARMOS  (button id lp-enter)",
        ("Plays the lp-transition wipe, then navigates to the operator console (index.html).", 1),
        ("The note line under it (#lp-cta-note) is a live region: if entry cannot proceed it", 1),
        ("says so in words rather than failing silently.", 1),
    ], size=13.5, gap=4)
    note(s, "If the dots never leave 'unknown', the page loaded from the filesystem instead of "
            "the server. Always open the console via http://127.0.0.1:8770, never by "
            "double-clicking the HTML file.", y=6.4, color=WARN)

    # -------------------------------------------------- 4. console anatomy
    s = new_slide(prs, "Screen 2  -  the operator console, at a glance",
                  "web/index.html  -  a frozen 68 / 22 / 10 layout. Geometry never moves.",
                  accent=ACCENT)
    kpi_cards(s, [
        ("48 px", "Top bar: identity + run status", ACCENT),
        ("68 %", "Map: the live warehouse", TEAL),
        ("22 %", "Right rail: 5 inspector panels", VIOLET),
        ("10 %", "Telemetry strip: 7 KPIs", OK),
    ], y=1.5, h=1.35)
    bullets(s, [
        "WHY THE GEOMETRY IS FIXED",
        ("The map is the product, so it keeps two thirds of the screen at all times. Panels never", 1),
        ("steal space from it and never cover it. The rail has a 320 px minimum width; below", 1),
        ("1280 px it becomes an overlay drawer opened by the 'Panels' button.", 1),
        "",
        "THE DEGRADATION BANNER  (id banner)",
        ("Sits ABOVE the shell in normal flow, so it can only ever push content down - it can", 1),
        ("never cover the map. It states a CAUSE and an ACTION, and it is not a toast: an", 1),
        ("operator who looked away can still read it. Dismiss with the x on its right.", 1),
        "",
        "PANELS ARE CLOSED ON ENTRY",
        ("By design. You land on the map, not on a wall of text. Open the rail when you want", 1),
        ("detail; the Fleet tab is pre-selected behind it.", 1),
    ], y=3.1, size=13, gap=3)

    # ------------------------------------------------------ 5. top bar
    s = new_slide(prs, "Top bar  -  identity, commands, run status",
                  "Left to right, exactly as rendered", accent=ACCENT)
    table(s,
          ["Control / readout", "id", "What it means / does"],
          [
              ["SWARMOS  +  Fleet Coordination", "brand", "Product identity. Not clickable."],
              ["Commands   Ctrl K", "btn-palette", "Opens the command palette dialog. Same as pressing Ctrl+K / Cmd+K."],
              ["Panels", "btn-rail-toggle", "Only rendered below 1280 px width. Opens/closes the rail as an overlay drawer."],
              ["Link  +  dot  +  Offline", "link-dot / link-text", "Live transport health. Offline = the browser is not receiving state frames. THIS IS THE FIRST THING TO CHECK."],
              ["Scenario", "hdr-scenario", "Which scenario the running sim was started with. -- before a run."],
              ["Seed", "hdr-seed", "The RNG seed. Same scenario + same seed + same fleet = byte-identical run. This is what makes the demo reproducible."],
              ["Tick", "hdr-tick", "Discrete sim steps elapsed. The loop runs at 10 Hz, so 1 tick = 100 ms of sim time."],
              ["Sim clock", "hdr-clock", "Sim time in seconds. = tick / 10. Not wall-clock time."],
          ],
          y=1.42, size=10.5, col_widths=[2.9, 1.7, 7.0])
    note(s, "Link Offline while Tick is frozen means the server died or the socket dropped. "
            "Press  r  to force an immediate reconnect attempt.", y=6.5, color=WARN)

    # ---------------------------------------------------------- 6. the map
    s = new_slide(prs, "The map  -  what is actually drawn",
                  "Four stacked canvases. Only the robot layer repaints per frame; the static "
                  "floor is painted once per viewport change.", accent=TEAL)
    table(s,
          ["Layer", "id", "Contents"],
          [
              ["Static", "layer-static", "Warehouse floor: grid, aisles, racks, charging docks, zone boundaries. Repainted only on resize / zoom / pan."],
              ["Paths", "layer-paths", "Planned routes and waypoints of robots that have published a movement intent."],
              ["Robots", "layer-robots", "Every robot, drawn in its state colour. Repaints every frame."],
              ["Hit", "layer-hit", "Transparent interaction surface. Owns all mouse and keyboard input. Focusable (tabindex 0)."],
          ],
          y=1.42, size=11, col_widths=[1.5, 2.0, 8.1])
    bullets(s, [
        "LEVEL OF DETAIL",
        ("Below 6 screen-pixels per metre, robots degrade to plain dots. This is not a bug: at", 1),
        ("fleet-wide zoom you are reading the pattern of colour, not individual chassis. Zoom in", 1),
        ("to get the full glyph with heading, payload and comm ring.", 1),
    ], y=4.35, size=13, gap=3)
    note(s, "Overlay corners: top-left = state legend with live counts. top-right = zoom controls. "
            "bottom-left = Zoom / Cursor / Render fps readout.", y=5.55, color=MUTED)

    # ------------------------------------------- 7. map controls
    s = new_slide(prs, "Map controls  -  mouse and keyboard",
                  "The hit canvas owns all of these", accent=TEAL)
    two_col(s,
            "Mouse",
            [
                "Hover a robot",
                ("Cursor becomes a pointer and a tooltip identifies it. Hovering is free - it does not change selection.", 1),
                "Click a robot",
                ("SELECTS it. This is the single most important interaction in the whole UI: it drives the Decision inspector.", 1),
                "Click empty floor",
                ("Clears the selection.", 1),
                "Drag (mousedown + move)",
                ("Pans the view. Cursor becomes 'grabbing'. Default cursor over floor is a crosshair.", 1),
                "Scroll wheel",
                ("Zooms about the cursor position.", 1),
            ],
            "Keyboard",
            [
                "+   /   -    (buttons btn-zoom-in / btn-zoom-out)",
                ("Zoom in / out a step.", 1),
                "Fit   (button btn-zoom-fit)",
                ("Fit the whole warehouse to the viewport.", 1),
                "0",
                ("Same as Fit. Reset zoom and pan. Use this whenever you get lost.", 1),
                "Arrow keys",
                ("Pan the map (the hit canvas must have focus).", 1),
                "Esc",
                ("Clear the selected robot.", 1),
                "r  /  R",
                ("Force an immediate transport reconnect.", 1),
                "Ctrl K  /  Cmd K",
                ("Open the command palette.", 1),
            ],
            y=1.45, h=4.9, accent_l=ACCENT, accent_r=TEAL, size=11.5)
    note(s, "Single-key shortcuts are suppressed while you are typing in a field, while a "
            "modifier is held, and while the palette is open. Typing 'r' in the Seed box will "
            "never reconnect the socket.", y=6.52, color=MUTED)

    # ------------------------------------------------- 8. state colours
    s = new_slide(prs, "The state colour language",
                  "Eight robot states. Learn these and the map reads itself.",
                  accent=VIOLET)
    swatches(s, [
        (FG.__class__(0xC8, 0xD2, 0xDC), "MOVING",
         "Nominal: driving its route. Deliberately the quietest colour on screen - normal is not news."),
        (FG.__class__(0xE5, 0x48, 0x4D), "BLOCKED",
         "The safety kernel VETOED motion. Red. A rising BLOCKED count is the deadlock signature."),
        (FG.__class__(0xF5, 0xA6, 0x23), "WAITING",
         "Yielded to a peer and will resume. Amber. This is healthy coordination, not a fault."),
        (FG.__class__(0x3E, 0x9B, 0xFF), "CHARGING",
         "At a dock, taking charge. Out of the task pool for now."),
        (FG.__class__(0x2F, 0x6F, 0x4E), "AVAILABLE",
         "Idle, awaiting assignment. Drawn as an OUTLINE only, never filled - idle should not draw the eye."),
        (FG.__class__(0x6E, 0x3A, 0x3C), "FAILED",
         "Dead robot. Desaturated on purpose: it is a fact to route around, not an alarm to panic at."),
        (PURPLE, "QUARANTINED",
         "A rogue agent the fleet has contained (X-10). Peers have collectively stopped trusting it."),
        (TEAL, "SOVEREIGN",
         "Radio lost, still working alone (X-01). The headline resilience behaviour - it did not stop."),
    ], y=1.5, h=0.44, gap=0.17, label_size=11.5)
    note(s, "Order is fixed everywhere (legend, roster, composition bars): MOVING, BLOCKED, "
            "WAITING, CHARGING, AVAILABLE, FAILED, QUARANTINED, SOVEREIGN.",
         y=6.45, color=MUTED)

    # ------------------------------------------------ 9. telemetry strip
    s = new_slide(prs, "Telemetry strip  -  the seven numbers along the bottom",
                  "Exactly ONE hero metric, because throughput is the question the product answers",
                  accent=OK)
    table(s,
          ["Metric", "Unit", "How to read it"],
          [
              ["Tasks per minute  (HERO)", "/min", "Throughput. The headline. Higher is better. Rendered larger than everything else on purpose."],
              ["Completed", "count", "Total tasks finished this run. Monotonic - it only goes up."],
              ["Collisions", "count", "MUST STAY 0. Any non-zero value is a safety-kernel failure and invalidates the run."],
              ["Tick budget p95", "ms", "95th-percentile compute per tick. The budget is 100 ms (10 Hz). Above 100 means the edge deadline was missed."],
              ["Avg completion", "s", "Mean task cycle time. Lower is better."],
              ["Verdicts", "count", "Safety-kernel rulings issued. Evidence the kernel is actually arbitrating, not idle."],
              ["Replans", "count", "Route recomputations. Some is healthy adaptation; a spike means the floor got congested."],
          ],
          y=1.42, size=11, col_widths=[3.1, 1.2, 7.3])
    note(s, "All seven read  --  before the first state frame. That is 'no data', not zero.",
         y=6.45, color=MUTED)

    # ------------------------------------------------ 10. rail overview
    s = new_slide(prs, "The right rail  -  five panels",
                  "Tabs, left to right. Arrow Left / Right moves between them when a tab has focus.",
                  accent=VIOLET)
    table(s,
          ["Tab label", "Panel heading", "The one question it answers"],
          [
              ["Fleet", "Fleet", "WHAT is the fleet doing right now, robot by robot?"],
              ["Decision", "Decision inspector", "WHY did this specific robot do that, this tick?"],
              ["Lab", "Lab", "Drive the simulation: start, pause, step, stop, inject faults."],
              ["Compare", "Compare", "Is SWARMOS actually better than the baseline policy?"],
              ["Analytics", "Analytics", "How are the four key metrics trending over the run?"],
          ],
          y=1.45, size=12, col_widths=[1.8, 2.7, 7.7])
    bullets(s, [
        "TWO THINGS WORTH KNOWING",
        ("The tab says 'Decision' but the panel heading says 'Decision inspector'. Same panel.", 1),
        ("Only the VISIBLE panel re-renders. Hidden panels cost nothing per frame - which is why", 1),
        ("the map holds its frame rate with a full fleet and the rail open.", 1),
    ], y=4.4, size=13, gap=3)
    note(s, "The rail starts CLOSED. Nothing is broken - open it from 'Panels', or let a "
            "palette command switch you to a tab.", y=5.6, color=MUTED)

    # ------------------------------------------------ 11. fleet panel
    s = new_slide(prs, "Panel 1  -  Fleet",
                  "Three stacked sections: composition, resilience, roster", accent=ACCENT)
    bullets(s, [
        "FLEET COMPOSITION",
        ("A count per state, in the fixed state order. This is your instant health read:", 1),
        ("mostly MOVING = healthy. A growing BLOCKED column = investigate now.", 1),
        "",
        "RESILIENCE  -  the three rows that prove the differentiators",
        ("Sovereign (radio lost)   robots that lost comms and kept working alone (X-01)", 1),
        ("Contained (rogue)        robots the fleet quarantined as adversarial (X-10)", 1),
        ("Failed                   robots that are dead", 1),
        ("These are the rows to point at after you inject a fault. They are the demo.", 1),
        "",
        "ROSTER",
        ("One row per robot. Sort control offers: Sort by id / Sort by state / Sort by battery.", 1),
        ("'Sort by state' groups the problems together; 'Sort by battery' finds the robot about", 1),
        ("to drop out. Click a row to select that robot - it drives the Decision inspector,", 1),
        ("exactly like clicking it on the map.", 1),
    ], size=13, gap=3)
    note(s, "Cold start: \"No robots are reporting.\" / \"Start a scenario in the Lab tab to "
            "populate the fleet.\"", y=6.5, color=MUTED)

    # ------------------------------------------- 12. inspector - chain
    s = new_slide(prs, "Panel 2  -  Decision inspector: the decision chain",
                  "The single most important explanatory screen in the product",
                  accent=BAD)
    bullets(s, [
        "HEADING:  <robot_id>  -  tick <n>      then a VERDICT block: the kind, and its reason.",
        "",
        "THEN THREE STAGES, TOP TO BOTTOM  -  this is the safety argument made visible:",
    ], y=1.4, h=1.0, size=13, gap=4)
    table(s,
          ["Stage", "Shows", "Read it as"],
          [
              ["Advisory", "The ML layer's proposed action, or 'none'",
               "A SUGGESTION. If it made no proposal you see: \"ML layer made no proposal this tick. It is never required to.\" The ML is optional by construction."],
              ["Binding", "Safety kernel: <verdict kind>",
               "THE DECISION. Either \"Kernel concurred with the proposal. It still had the final word.\" or \"Kernel OVERRODE the advisory <kind>. The kernel verdict is final.\""],
              ["Applied", "speed scale <0.00 - 1.00>",
               "WHAT THE WHEELS DID. \"Scale 0 means a full stop was commanded for this tick.\""],
          ],
          y=2.5, size=11.5, col_widths=[1.5, 3.0, 7.7])
    note(s, "This is the answer to 'can you trust an ML-driven fleet?'. The learned layer only "
            "ever advises; a deterministic safety kernel is always binding; and when the two "
            "disagree the override is shown to you in plain words.", y=5.9, color=BAD)

    # ------------------------------ 13. inspector - state / integrity
    s = new_slide(prs, "Panel 2  -  Decision inspector: the rest of the panel",
                  "State, Integrity and Movement intent sections", accent=BAD)
    two_col(s,
            "State  /  Movement intent",
            [
                "Status        state chip, in its state colour",
                "Position      x, y in metres (2 dp)",
                "Velocity      m/s (2 dp)",
                "Battery       % (0 dp)",
                "Task          current task id, or --",
                "Sim time      seconds (1 dp)",
                "",
                "Target        destination x, y",
                "Waypoints     how many points remain in the route",
                "ETA           seconds to arrival",
                "Path version  increments on every replan. A fast-rising",
                ("              version means this robot keeps being forced", 1),
                ("              to re-route - congestion or a live obstacle.", 1),
                "",
                "If idle: \"No movement intent published.\" /",
                ("\"The robot is idle or awaiting a task assignment.\"", 1),
            ],
            "Integrity  (the rogue-containment evidence)",
            [
                "Ruling      the fleet's collective judgement on this robot",
                "Reason      why it was accused",
                "Witnesses   WHICH PEERS corroborated it. Containment is",
                ("            never one robot's word - it is a quorum.", 1),
                "At tick     when the ruling landed",
                "",
                "Three possible states:",
                ("Contained, with reason + witnesses + tick", 1),
                ("\"Under suspicion, not contained\"  - flagged, still trusted", 1),
                ("\"No accusation\"                   - clean", 1),
                "",
                "When a robot is lying about itself you also get:",
                ("Claimed   the position it BROADCAST", 1),
                ("Actual    the position it IS at", 1),
                ("Seeing those two disagree is the rogue, caught.", 1),
            ],
            y=1.42, h=4.95, accent_l=ACCENT, accent_r=PURPLE, size=11)
    note(s, "Empty states: \"No robot selected.\" / \"Click a robot on the map, or pick one from "
            "the Fleet roster.\"  -  and if it vanishes mid-run, it says so instead of showing "
            "stale numbers.", y=6.55, color=MUTED)

    # ---------------------------------------------------- 14. lab panel
    s = new_slide(prs, "Panel 3  -  Lab  (this is the driver's seat)",
                  "Configure a run, drive the tick loop, inject faults, prove determinism",
                  accent=WARN)
    table(s,
          ["Control", "id", "Default", "What it does"],
          [
              ["Scenario", "lab-scenario", "from server", "Which warehouse scenario. Built-in fallbacks: rush_50, narrow_aisle_deadlock, blocked_aisle. The hint line tells you whether the list came from the server or is the built-in fallback."],
              ["Fleet size", "lab-fleet", "24", "Number of robots, 1 - 50."],
              ["Seed", "lab-seed", "11", "RNG seed. Same scenario + seed + fleet = identical run, every time."],
              ["Message integrity", "lab-integrity", "Off", "Off, or 'Signed messages and sentinel council' - turns on cryptographic message signing and the peer council that judges rogues."],
              ["Start", "lab-start", "-", "Begin the run with the settings above."],
              ["Pause", "lab-pause", "-", "Freeze the 10 Hz tick loop. The map stays; time stops."],
              ["Step", "lab-step", "-", "Advance exactly ONE tick = 100 ms. The move for explaining a single decision."],
              ["Stop", "lab-stop", "-", "Halt the run and release the fleet."],
          ],
          y=1.4, size=10, col_widths=[2.0, 1.5, 1.2, 7.5])
    note(s, "Pause, then Step, then open the Decision inspector. That is how you show a judge "
            "exactly why one robot yielded, frame by frame.", y=6.3, color=WARN)

    # ------------------------------------------- 15. lab - faults
    s = new_slide(prs, "Panel 3  -  Lab: fault injection and determinism",
                  "The differentiation is not the task count. It is what happens after you "
                  "break something.", accent=WARN)
    bullets(s, [
        "FAULT  (select lab-fault, then press Inject)",
    ], y=1.35, h=0.4, size=13)
    table(s,
          ["Fault (exact label)", "What to watch after you inject it"],
          [
              ["Robot failure (kill one robot)",
               "Its state goes FAILED (desaturated). Peers re-route around it and its task is picked up. Fleet -> Resilience -> Failed increments."],
              ["Comm blackout (cut one robot's radio 6 s)",
               "It turns SOVEREIGN (teal) and KEEPS WORKING. This is X-01, the headline resilience claim. Watch Resilience -> Sovereign (radio lost)."],
              ["Link impairment (drops and latency, fleet-wide)",
               "The degradation banner appears naming cause and action. Throughput degrades gracefully instead of the fleet stalling."],
              ["Block an aisle (static obstacle)",
               "Robots facing it go BLOCKED (red) then WAITING (amber) and replan. Path version climbs in the inspector."],
              ["Rogue agent (adversarial robot)",
               "It starts lying. The council accuses it, witnesses corroborate, and it turns QUARANTINED (purple). This is X-10. Open Integrity to see Claimed vs Actual."],
          ],
          y=1.85, size=10.5, col_widths=[3.3, 8.9])
    bullets(s, [
        "DETERMINISM PROOF  -  Capture hash  /  Compare now",
        ("Capture hash takes the trace hash of the run so far. Run the same scenario, seed and", 1),
        ("fleet again, capture again, then Compare now. Identical hashes = the run is bit-for-bit", 1),
        ("reproducible. That is how a distributed system is made auditable.", 1),
    ], y=4.85, size=12.5, gap=3)

    # ---------------------------------------------------- 16. compare
    s = new_slide(prs, "Panel 4  -  Compare  (the co-simulation)",
                  "Two policies, the SAME tasks, side by side. The honest-benchmark screen.",
                  accent=OK)
    bullets(s, [
        "CONTROLS",
        ("Horizon (ticks)   id cosim-ticks   -  how far to simulate both arms.", 1),
        ("Run comparison    starts both arms over the same task stream.", 1),
        ("Stop              halts the comparison.", 1),
        ("Inject into both arms  -  a row of fault buttons. The point is FAIRNESS: the same", 1),
        ("                         shock is delivered to SWARMOS and to the baseline.", 1),
        "",
        "WHAT IT SHOWS",
        ("Diverged at   the tick where the two arms first stopped being identical. Before that", 1),
        ("              tick the comparison is exact, not approximate.", 1),
        ("State / Tick  where the comparison currently is.", 1),
        ("Delta rows    per-KPI difference. A row only appears once that KPI actually differs.", 1),
        ("Replay        two labelled tracks: SwarmOS and Baseline.", 1),
        "",
        "EMPTY STATES ARE HONEST HERE, AND THAT MATTERS",
        ("\"No comparison has been run.\" / \"Press Run comparison to simulate both policies over", 1),
        ("the same tasks.\"", 1),
        ("\"No metric has separated the two arms yet.\" / \"Both arms are still warming up; rows", 1),
        ("appear as soon as a KPI differs.\"  -  it refuses to show a win that has not happened.", 1),
    ], size=12.5, gap=3)

    # --------------------------------------------------- 17. analytics
    s = new_slide(prs, "Panel 5  -  Analytics",
                  "Four charts. Four questions. Nothing else.", accent=VIOLET)
    table(s,
          ["Chart (exact title)", "Unit", "The question", "Good / bad"],
          [
              ["Tasks per minute", "-", "Is it getting work done?", "Higher is better. A flat line at zero means the fleet is stuck."],
              ["Robots blocked", "count", "Is it deadlocking?", "Rising is BAD. A sustained climb is the deadlock signature."],
              ["Compute p95", "ms", "Does it hold the edge deadline?", "Must stay under the dashed 100 ms tick budget line drawn on the chart."],
              ["Messages per robot per tick", "-", "Does comms scale?", "Must stay FLAT as fleet size grows. A rising line means O(n^2) chatter - the thing distributed coordination is supposed to avoid."],
          ],
          y=1.45, size=11, col_widths=[2.9, 0.9, 3.0, 5.4])
    bullets(s, [
        "SERIES COLOURS:  Tasks/min blue #5B8FF9  -  Blocked green #61DDAA  -  "
        "Compute p95 amber #F6BD16  -  Messages violet #7262FD",
        ("The only dashed grey line (#63707D) is a reference, never data. On Compute p95 its", 1),
        ("legend key reads '100 ms tick budget'. Comparison lines are always tertiary so you", 1),
        ("never mistake a baseline for a measurement.", 1),
    ], y=4.55, size=12.5, gap=3)
    note(s, "Cold start: \"No samples recorded.\" / \"Start a run in the Lab tab; charts fill as "
            "ticks arrive.\"", y=6.5, color=MUTED)

    # ------------------------------------------- 18. command palette
    s = new_slide(prs, "The command palette  -  Ctrl K",
                  "Built so a demo never depends on finding a small button under pressure",
                  accent=ACCENT)
    table(s,
          ["Command", "Description (as shown)", "Key"],
          [
              ["Start run", "Start the configured scenario", "-"],
              ["Pause / resume", "Toggle the 10 Hz tick loop", "-"],
              ["Step one tick", "Advance exactly 100 ms of sim time", "-"],
              ["Stop run", "Halt the run and release the fleet", "-"],
              ["Fit map to warehouse", "Reset zoom and pan", "0"],
              ["Clear selection", "Deselect the inspected robot", "Esc"],
              ["Open decision inspector", "Show the advisory / binding / applied chain", "-"],
              ["Open analytics", "Throughput, blocking, compute budget, message load", "-"],
          ],
          y=1.45, size=11.5, col_widths=[3.0, 7.2, 1.0])
    bullets(s, [
        "HOW TO DRIVE IT:  Ctrl K (or Cmd K) opens  -  type to filter  -  Up / Down to move  -  "
        "Enter to run  -  Esc to close.",
        ("The hint row at the bottom of the dialog states exactly that, so you never have to", 1),
        ("remember it. Placeholder text: \"Type a command...\"", 1),
    ], y=4.95, size=12.5, gap=3)

    # --------------------------------------- 19. reading numbers
    s = new_slide(prs, "Reading the numbers correctly",
                  "Formatting rules that change what a value MEANS", accent=OK)
    two_col(s,
            "Formatting contract",
            [
                "--            no data. NOT zero. Never zero-as-unknown.",
                "0             a real, measured zero.",
                "Integers      thousands separators, en-US.",
                "Metres        2 decimal places.",
                "Seconds       1 decimal place.",
                "Percent       0 decimal places.",
                "Long hashes   first8...last8, so a trace hash fits",
                ("              in a panel without lying about its value.", 1),
                "",
                "Tick vs clock",
                ("1 tick = 100 ms of SIM time. Sim clock = tick / 10.", 1),
                ("Neither is wall-clock time. A paused run has a", 1),
                ("frozen clock and a live UI.", 1),
            ],
            "Order of checks when something looks wrong",
            [
                "1. Top bar -> Link. Offline? press r to reconnect.",
                "2. Top bar -> Tick. Frozen? the run is paused or dead.",
                "3. Banner. It names the cause AND the action. Read it.",
                "4. Strip -> Collisions. Non-zero invalidates the run.",
                "5. Strip -> Tick budget p95. Over 100 ms = deadline miss.",
                "6. Analytics -> Robots blocked. Climbing = deadlock.",
                "7. Fleet -> Resilience. Sovereign / Contained / Failed",
                ("   tells you which fault is currently in play.", 1),
                "8. Select the robot, open Decision inspector, and read",
                ("   the Advisory / Binding / Applied chain. That always", 1),
                ("   explains the individual behaviour.", 1),
            ],
            y=1.45, h=4.9, accent_l=OK, accent_r=WARN, size=11.5)
    note(s, "If a panel is blank, read its two lines before doing anything else. Every empty "
            "state in this UI names a cause and an action.", y=6.52, color=MUTED)

    # ------------------------------------------- 20. demo click path
    s = new_slide(prs, "The demo click-path",
                  "The reference run is rush_50, seed 11, fleet 8  -  a MEASURED parity point, "
                  "not a flattering one", accent=TEAL)
    steps(s, [
        ("./run.sh --demo",
         "Server starts, /api/health is polled (never a blind sleep), browser opens, reference run already ticking."),
        ("Landing page: press ENTER SWARMOS",
         "Check FLEET STATUS and AMR NETWORK are live before you go in."),
        ("Console opens on the map, panels closed",
         "Top bar: Link online, Scenario rush_50, Seed 11, Tick climbing. Strip: Tasks per minute rising, Collisions 0."),
        ("Press 0 to fit the warehouse",
         "Read the colour pattern: mostly quiet MOVING, occasional amber WAITING. Amber is healthy yielding."),
        ("Click any robot, open the Decision tab",
         "Advisory / Binding / Applied. Say out loud: the ML only advises, the kernel is always binding."),
        ("Lab tab: inject 'Comm blackout (cut one robot's radio 6 s)'",
         "The robot turns teal SOVEREIGN and KEEPS WORKING. Fleet -> Resilience -> Sovereign increments. This is X-01."),
        ("Lab tab: inject 'Rogue agent (adversarial robot)'",
         "It turns purple QUARANTINED. Open Integrity: Ruling, Reason, Witnesses, and Claimed vs Actual position. This is X-10."),
        ("Compare tab: Run comparison, then inject into both arms",
         "Same shock, both policies. Point at 'Diverged at' and the delta rows, not at raw task count."),
        ("Analytics tab",
         "Messages per robot per tick stays FLAT, Compute p95 stays under the 100 ms budget line."),
        ("Lab tab: Capture hash, re-run, Capture hash, Compare now",
         "Identical trace hashes. The run is reproducible and auditable."),
    ], y=1.42, gap=0.53, size=12)

    # -------------------------------------------- 21. honest limits
    s = new_slide(prs, "Honest limitations  -  say these before you are asked",
                  "Credibility is a feature. So is knowing what the UI does not claim.",
                  accent=WARN)
    bullets(s, [
        "THROUGHPUT IS AT PARITY, NOT AHEAD",
        ("At fleet 8 on rush_50 over 1800 ticks the measured result is 20 completions against the", 1),
        ("baseline's 22. That is deliberately the demo default. The claim is NOT 'more tasks per", 1),
        ("minute in the nominal case' - it is what survives a fault. Show the fault, not the count.", 1),
        "",
        "THIS IS A SIMULATION",
        ("Robot dynamics, radio behaviour and task arrival are modelled, not measured on hardware.", 1),
        ("The map draws an AMR mobile base because that is what the simulation actually models.", 1),
        "",
        "SCOPE OF THE UI",
        ("Dark theme only, no theme switch. No authentication, no multi-user, no persistence of", 1),
        ("past runs beyond the live session. Desktop-first: below 1280 px the rail becomes an", 1),
        ("overlay drawer rather than re-flowing.", 1),
        "",
        "NO BUILD STEP, BY CHOICE",
        ("Native ES modules, no bundler. Open the source and what you read is what runs - which is", 1),
        ("also why it must be served over HTTP, not opened as a file.", 1),
    ], size=12.5, gap=3)
    note(s, "Every number on these screens comes from the running engine. Nothing in this UI is "
            "mocked, and nothing is rendered as 0 when it is unknown.", y=6.6, color=TEAL)

    # ---------------------------------------------- 22. one-page recap
    s = new_slide(prs, "One-page recap",
                  "If you remember five things, remember these", accent=TEAL)
    kpi_cards(s, [
        ("Ctrl K", "Every action, without hunting for a button", ACCENT),
        ("0", "Fit the map when you get lost", TEAL),
        ("Esc", "Clear the selected robot", VIOLET),
        ("r", "Force a transport reconnect", WARN),
    ], y=1.5, h=1.3)
    bullets(s, [
        "1.  CLICK A ROBOT. Nothing in the Decision inspector works until you do. Map click or",
        ("    Fleet roster row - both select.", 1),
        "2.  --  MEANS NO DATA.  0 means a measured zero. The UI will not blur that distinction.",
        "3.  RED IS A VETO, AMBER IS A YIELD. BLOCKED means the safety kernel stopped the robot;",
        ("    WAITING means it politely gave way and will resume. Amber is the system working.", 1),
        "4.  TEAL AND PURPLE ARE THE DIFFERENTIATORS. Teal SOVEREIGN = lost its radio and kept",
        ("    working (X-01). Purple QUARANTINED = the fleet contained a rogue (X-10).", 1),
        "5.  THE KERNEL IS ALWAYS BINDING. Advisory proposes, Binding decides, Applied acts. The",
        ("    ML layer is never required and never final. That is the whole trust argument.", 1),
    ], y=3.15, size=13, gap=5)
    note(s, "Start: ./run.sh --demo     Console: http://127.0.0.1:8770     "
            "Reference run: rush_50, seed 11, fleet 8", y=6.55, color=TEAL)

    out = os.path.join(os.path.dirname(_HERE), OUT)
    prs.save(out)
    print("wrote %s  (%d slides)" % (out, len(prs.slides._sldIdLst)))
    return out


if __name__ == "__main__":
    build()

# File contains AI-generated response based on internal company sources
