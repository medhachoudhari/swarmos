"""X-01 UI layer: a sovereign robot must be visibly distinct from a healthy
one, from a contained one, and from a dead one.

Colour choice: desaturated teal. Not purple (that is QUARANTINED, a judgement
the fleet made) and not red or amber (those mean the safety kernel is actively
holding motion back). A sovereign robot is working correctly, just alone, so
the colour has to read as 'unusual but fine'.

Every substitution asserts it matched exactly once, and every JS file is
checked with `node --check` by the caller afterwards.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, f"{label}: expected 1 match, found {count}"
    return text.replace(old, new)


def edit(rel, fn):
    p = ROOT / rel
    src = p.read_text()
    out = fn(src)
    p.write_text(out)
    print(f"patched {rel}")


# ---------------------------------------------------------------- tokens.css
def tokens(s):
    return sub(
        s,
        "  --state-quarantined: #A855C4; /* rogue containment (X-10) */\n",
        "  --state-quarantined: #A855C4; /* rogue containment (X-10) */\n"
        "  --state-sovereign: #4FB3A6;   /* radio lost, still working alone (X-01) */\n",
        "tokens: sovereign colour",
    )


# ------------------------------------------------------------------ store.js
def store(s):
    return sub(
        s,
        '  "AVAILABLE", "FAILED", "QUARANTINED",\n',
        '  "AVAILABLE", "FAILED", "QUARANTINED", "SOVEREIGN",\n',
        "store: STATES",
    )


# -------------------------------------------------------------------- map.js
def mapjs(s):
    s = sub(
        s,
        '  STATE_COLOR.QUARANTINED = css("--state-quarantined");\n',
        '  STATE_COLOR.QUARANTINED = css("--state-quarantined");\n'
        '  STATE_COLOR.SOVEREIGN = css("--state-sovereign");\n',
        "map: STATE_COLOR",
    )
    s = sub(
        s,
        'const FOOTPRINT_M = 0.70;         // pair footprint = collision distance\n',
        'const FOOTPRINT_M = 0.70;         // pair footprint = collision distance\n'
        '// X-01. A sovereign robot is arbitrated against a wider hard-stop:\n'
        '// HARD_STOP_M 0.75 + SOVEREIGN_MARGIN_M 0.35, mirrored from swarm_policy.py.\n'
        'const SOVEREIGN_ENVELOPE_M = 1.10;\n',
        "map: sovereign envelope constant",
    )
    s = sub(
        s,
        """      // Safety footprint ring, only for states where separation is the story.
      if (r.status === "BLOCKED" || r.status === "WAITING") {
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.28;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(sx, sy, (FOOTPRINT_M / 2) * s, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
""",
        """      // Safety footprint ring, only for states where separation is the story.
      // SOVEREIGN draws the WIDER envelope it is actually held to, because the
      // whole claim of the mode is 'less information, so more clearance'. A
      // ring that matched the normal footprint would hide the claim.
      if (r.status === "BLOCKED" || r.status === "WAITING" || r.status === "SOVEREIGN") {
        const ringM = r.status === "SOVEREIGN" ? SOVEREIGN_ENVELOPE_M : FOOTPRINT_M / 2;
        ctx.strokeStyle = color;
        ctx.globalAlpha = 0.28;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(sx, sy, ringM * s, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
""",
        "map: footprint ring",
    )
    return s


# -------------------------------------------------------------- panels/lab.js
def lab(s):
    return sub(
        s,
        '  { id: "comm_blackout", label: "Comm blackout (drop all links 3 s)" },\n',
        '  { id: "comm_blackout", label: "Comm blackout (cut one robot\'s radio 6 s)" },\n',
        "lab: blackout label",
    )


# ------------------------------------------------------------ panels/fleet.js
def fleet(s):
    s = sub(
        s,
        'import { int, metres, pct } from "../format.js";\n',
        'import { DASH, int, metres, pct } from "../format.js";\n',
        "fleet: import DASH",
    )
    s = sub(
        s,
        '      <div id="state-counts"></div>\n',
        '      <div id="state-counts"></div>\n'
        '      <div class="panel__section">\n'
        '        <h2 class="panel__title">Resilience</h2>\n'
        '        <div id="resilience"></div>\n'
        '      </div>\n',
        "fleet: resilience container",
    )
    s = sub(
        s,
        """    this.el.querySelector("#state-counts").innerHTML = STATES
      .filter((s) => counts[s] > 0)
      .map((s) => `<div class="kv"><span class="kv__k">${s}</span><span class="kv__v num">${int(counts[s])}</span></div>`)
      .join("");
""",
        """    this.el.querySelector("#state-counts").innerHTML = STATES
      .filter((s) => counts[s] > 0)
      .map((s) => `<div class="kv"><span class="kv__k">${s}</span><span class="kv__v num">${int(counts[s])}</span></div>`)
      .join("");

    // Resilience counters come from the arbiter's KPIs, not from the robot
    // states, so they are reported even when the count is zero: 'zero robots
    // contained' is a real and reassuring reading, unlike a missing value,
    // which renders as a dash and never as a fabricated zero.
    const k = store.kpis || {};
    const shown = (v) => (v === null || v === undefined ? DASH : int(v));
    this.el.querySelector("#resilience").innerHTML = `
      <div class="kv"><span class="kv__k">Sovereign (radio lost)</span>
        <span class="kv__v num">${shown(k.robots_sovereign)}</span></div>
      <div class="kv"><span class="kv__k">Contained (rogue)</span>
        <span class="kv__v num">${shown(k.robots_rogue)}</span></div>
      <div class="kv"><span class="kv__k">Failed</span>
        <span class="kv__v num">${shown(k.robots_failed)}</span></div>
      <span class="chain__note">A sovereign robot lost contact with every peer and is
        navigating on a tightened envelope at half speed. It is still working.</span>
""" + '`;\n',
        "fleet: resilience update",
    )
    return s


# ------------------------------------------------------- panels.css / shell.css
def panels_css(s):
    return sub(
        s,
        '.roster__row[data-state="QUARANTINED"] { border-left-color: var(--state-quarantined); }\n',
        '.roster__row[data-state="QUARANTINED"] { border-left-color: var(--state-quarantined); }\n'
        '.roster__row[data-state="SOVEREIGN"]   { border-left-color: var(--state-sovereign); }\n',
        "panels.css: roster sovereign",
    )


def shell_css(s):
    return sub(
        s,
        '.chip[data-state="QUARANTINED"] { color: var(--state-quarantined); }\n',
        '.chip[data-state="QUARANTINED"] { color: var(--state-quarantined); }\n'
        '.chip[data-state="SOVEREIGN"]   { color: var(--state-sovereign); }\n',
        "shell.css: chip sovereign",
    )


def main():
    edit("web/styles/tokens.css", tokens)
    edit("web/styles/panels.css", panels_css)
    edit("web/styles/shell.css", shell_css)
    edit("web/js/store.js", store)
    edit("web/js/map.js", mapjs)
    edit("web/js/panels/lab.js", lab)
    edit("web/js/panels/fleet.js", fleet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
