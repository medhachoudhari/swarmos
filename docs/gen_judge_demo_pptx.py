#!/usr/bin/env python3
"""Generate SWARMOS_JUDGE_DEMO_SIH26123.pptx.

A dedicated demo-day slide deck: one slide per feature to be shown to
judges, with the CLICK SEQUENCE and TALKING POINTS in the visible body, and
the full presenter script in the SPEAKER NOTES (View > Notes in PowerPoint /
LibreOffice Impress).

Deliberately plain-text based (no custom shapes) so it renders identically
in PowerPoint, LibreOffice Impress, and Google Slides.
"""
from __future__ import annotations

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

OUT = "SWARMOS_JUDGE_DEMO_SIH26123.pptx"

NAVY = RGBColor(0x12, 0x1E, 0x33)
TEAL = RGBColor(0x1F, 0x7A, 0x6C)
INK = RGBColor(0x22, 0x28, 0x30)
GREY = RGBColor(0x6B, 0x74, 0x7D)
WARN = RGBColor(0xB4, 0x3A, 0x2B)


def blank_slide(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def add_title(slide, text, *, color=NAVY, size=30, top=0.35):
    box = slide.shapes.add_textbox(Inches(0.55), Inches(top), Inches(12.2), Inches(1.0))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.color.rgb = color
    return box


def add_kicker(slide, text, *, top=0.05):
    box = slide.shapes.add_textbox(Inches(0.55), Inches(top), Inches(12.2), Inches(0.35))
    tf = box.text_frame
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text.upper()
    r.font.size = Pt(12)
    r.font.bold = True
    r.font.color.rgb = TEAL
    return box


def add_body(slide, blocks, *, top=1.3, width=12.2, left=0.55, size=14):
    """blocks: list of (label_or_None, text, color_or_None) tuples."""
    box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(5.6))
    tf = box.text_frame
    tf.word_wrap = True
    first = True
    for item in blocks:
        label, text, color = item
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(10)
        if label:
            r1 = p.add_run()
            r1.text = label + "  "
            r1.font.bold = True
            r1.font.size = Pt(size)
            r1.font.color.rgb = TEAL
        r2 = p.add_run()
        r2.text = text
        r2.font.size = Pt(size)
        r2.font.color.rgb = color or INK
    return box


def set_notes(slide, text):
    notes = slide.notes_slide
    notes.notes_text_frame.text = text


def feature_slide(prs, kicker, title, what, action, see, say, qa):
    s = blank_slide(prs)
    add_kicker(s, kicker)
    add_title(s, title)
    add_body(s, [
        ("WHAT IT IS:", what, None),
        ("CLICK SEQUENCE:", action, None),
        ("JUDGE SHOULD SEE:", see, None),
        ("SAY OUT LOUD:", '"%s"' % say, TEAL),
    ])
    notes = (
        "TALKING SCRIPT\n"
        "1) What it is: %s\n"
        "2) Click sequence: %s\n"
        "3) What to point at on screen: %s\n"
        "4) Say: \"%s\"\n\n"
        "ANTICIPATED QUESTION: %s\n"
        "ANSWER: %s\n"
    ) % (what, action, see, say, qa[0], qa[1])
    set_notes(s, notes)
    return s


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ---------------------------------------------------------------- title
    s = blank_slide(prs)
    bar = s.shapes.add_shape(1, Inches(0), Inches(0), Inches(0.18), Inches(7.5))
    bar.fill.solid()
    bar.fill.fore_color.rgb = TEAL
    bar.line.fill.background()

    box = s.shapes.add_textbox(Inches(0.9), Inches(2.4), Inches(11.5), Inches(1.4))
    p = box.text_frame.paragraphs[0]
    r = p.add_run()
    r.text = "SWARMOS"
    r.font.size = Pt(64)
    r.font.bold = True
    r.font.color.rgb = NAVY

    box2 = s.shapes.add_textbox(Inches(0.9), Inches(3.75), Inches(11.5), Inches(0.9))
    p2 = box2.text_frame.paragraphs[0]
    r2 = p2.add_run()
    r2.text = "Judge Demo Deck -- SIH26123 -- Live Feature Walkthrough"
    r2.font.size = Pt(22)
    r2.font.color.rgb = TEAL

    box3 = s.shapes.add_textbox(Inches(0.9), Inches(4.5), Inches(11.5), Inches(0.6))
    p3 = box3.text_frame.paragraphs[0]
    r3 = p3.add_run()
    r3.text = "Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots"
    r3.font.size = Pt(14)
    r3.font.color.rgb = GREY
    set_notes(s, (
        "OPENING (30 seconds). Do not open with jargon. Open with the map.\n"
        "\"This is SWARMOS -- a fleet of up to 50 warehouse robots, coordinating "
        "themselves with no central controller, and provably never colliding, "
        "even when we deliberately break things live.\"\n"
        "Then run the demo order in this deck. Every slide after this one maps "
        "to one live action + one talking point + one likely question."
    ))

    # ---------------------------------------------------------------- run order
    s = blank_slide(prs)
    add_kicker(s, "before you touch anything")
    add_title(s, "Demo Run Order")
    add_body(s, [
        (None, "1. ./run.sh  (or already running -- confirm http://127.0.0.1:8770/ loads)", None),
        (None, "2. Landing page -> ENTER SWARMOS -> dashboard loads with rush_50 / seed 11 / fleet 8", None),
        (None, "3. Command Palette (Ctrl+K) -> Start run  (or click Start demo run)", None),
        (None, "4. Let it run ~15 seconds so the judges see steady motion first, THEN start injecting faults", None),
        (None, "5. Work through the feature slides in this deck in order", None),
        (None, "6. Close with the Compare tab (baseline vs SWARMOS side by side)", None),
    ], size=16)
    set_notes(s, (
        "This is the safety net if anything is asked out of order. Never open "
        "with a fault injected -- always show 15+ seconds of calm, correct "
        "motion first so judges have a baseline mental model before you break "
        "anything on purpose."
    ))

    # ---------------------------------------------------------------- feature slides
    feature_slide(prs, "claim N5 / X-09",
        "The Safety Kernel Never Trusts the AI",
        "An ML advisory layer proposes speed changes. A small, auditable "
        "safety kernel independently decides the final verdict. The AI's "
        "opinion is display-only.",
        "Command Palette -> Start run. Then inject KILL ML fault.",
        "Collisions KPI stays at 0 before and after. Robots keep moving "
        "identically. The Decision panel still shows verdicts with no "
        "advisory attached.",
        "Killing the AI right now changes nothing about safety.",
        ("Isn't this just turning a feature off?",
         "It proves the safety-critical path has zero code dependency on the "
         "learned component -- enforced by a dedicated test "
         "(test_ml_fence.py), not just a demo trick."))

    feature_slide(prs, "the verdict ladder",
        "Graded Response, Not Binary Stop/Go",
        "PROCEED / SLOW / YIELD / WAIT / REROUTE -- the arbiter grades its "
        "intervention instead of stopping everyone at the first sign of "
        "conflict.",
        "Open the Decision tab, select two robots crossing paths.",
        "One robot SLOWs rather than stopping dead; the reason string names "
        "the peer and the exact distance.",
        "This grading is the single biggest reason we beat stop-and-wait on "
        "throughput.",
        ("Why not always stop to be maximally safe?",
         "Measured: an always-stop kernel vetoed 35% of all robot-ticks and "
         "wedged head-on traffic completely."))

    feature_slide(prs, "claim N9 / X-10",
        "Catching a Robot That Lies",
        "A robot can broadcast a false position. Peers' own honest sightings "
        "expose the mismatch, and the quorum layer quarantines the liar -- no "
        "central authority required.",
        "Inject ROGUE ROBOT fault on a moving robot.",
        "A dashed line from the robot's real body to its false claimed "
        "position -- the gap is the evidence. Ring turns quarantine colour "
        "within a few ticks.",
        "That gap you see is the lie, and the fleet caught it on its own.",
        ("What if an honest robot has sensor noise?",
         "The claim tolerance is set beyond realistic sensor noise but inside "
         "the danger threshold -- the fault's default offset is chosen to sit "
         "outside that tolerance."))

    feature_slide(prs, "claim X-01",
        "Surviving a Communications Blackout",
        "A robot that hears zero peers for half a second keeps working under "
        "a WIDER safety envelope and capped speed, instead of stopping and "
        "blocking the aisle.",
        "Inject COMM BLACKOUT on a moving robot.",
        "That robot's safety ring visibly widens and it slows, but keeps "
        "moving; after ~6 seconds it rejoins and the ring returns to normal.",
        "Less information means more caution, not a dead stop.",
        ("Isn't moving blind more dangerous than stopping?",
         "A stopped robot blocking an aisle is its own hazard for everyone "
         "else. The wider floor is measured to still hold zero collisions."))

    feature_slide(prs, "claim N10",
        "A Fair Fight: Baseline vs SWARMOS",
        "The classical stop-and-wait baseline and SWARMOS run on the "
        "IDENTICAL seed and task stream, side by side -- a paired, falsifiable "
        "comparison, not two runs that happened to differ.",
        "Open the Compare tab, pick rush_50, seed 11, press Start.",
        "Both fleets render on the same map (SWARMOS solid, baseline "
        "ghosted); the delta panel updates live.",
        "Same warehouse, same tasks, same seed -- only the coordination brain "
        "changed.",
        ("What is the current honest result?",
         "Throughput-time reduction target is >=20%; current measured mean "
         "is +2.0%, 95% CI [-5.9%, +9.8%] -- NOT MET, and we say so directly "
         "rather than hide it."))

    # ---------------------------------------------------------------- honesty slide
    s = blank_slide(prs)
    add_kicker(s, "say this proactively -- do not wait to be asked")
    add_title(s, "What We Are NOT Claiming", color=WARN)
    add_body(s, [
        (None, "Decentralised task auction (N1): Contract Net Protocol, 1980. "
               "We compete on measured result, not the idea.", None),
        (None, "Space-time reservation (N2): WHCA* / Kiva-class practice. "
               "Table stakes, not novel.", None),
        (None, "Deadlock ladder (N4): classical wait-for cycle detection "
               "(Coffman). The visibility of the ladder is the value-add.", None),
        (None, "Throughput-time criterion (C2, target >=20%): currently "
               "NOT MET. Reported honestly with the exact gap and next step.", None),
    ], size=16)
    set_notes(s, (
        "This slide is a credibility weapon, not a weakness. Say it BEFORE a "
        "judge finds it -- it proves the team can tell real novelty apart "
        "from standard practice, which is rarer at hackathon scale than a "
        "clean demo."
    ))

    # ---------------------------------------------------------------- closing
    s = blank_slide(prs)
    add_kicker(s, "close on this")
    add_title(s, "What IS Genuinely New")
    add_body(s, [
        ("N3", "Deterministic replay -- same seed, identical trace hash, "
               "provable live.", None),
        ("N5", "Simplex safety kernel with a firewalled AI advisory layer.", None),
        ("N9", "Adversarial robot containment -- Byzantine-tolerant "
               "allocation, rare at this scale.", None),
        ("N10", "Paired counterfactual co-simulation against a fairly-tuned "
                "classical baseline.", None),
    ], size=18)
    set_notes(s, (
        "End on the four claims rated GENUINE or GENUINE-NEW in our own "
        "internal review. Do not oversell the rest -- the honesty is the "
        "close."
    ))

    prs.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()

# File contains AI-generated response based on internal company sources
