"""Fix the five UI defects the browser screenshots exposed, and add the robot art.

Each fix is a real bug found by looking at a running page, not a cosmetic tweak:

A  VERDICTS read NaN in the bottom strip. kpis()["verdicts"] is a nested dict of
   per-kind counts, and int(dict) is NaN. Sum the counts instead.
B  Command palette shortcut badges rendered as full-width bordered bars. The
   class .palette__hint was doing two unrelated jobs: the footer hint bar and
   the per-row shortcut badge. Give the badge its own class.
C  Analytics "100 ms tick budget" legend text collided with the chart below it.
   Same root cause shape as B: .chart__key styled both the colour swatch and
   the text wrapper, so the wrapper was forced to 8x2 px and overflowed.
D  Every 4xx in the UI showed a bare "HTTP 400". The server writes its human
   message under "error" but transport.js read "detail", so the explanation was
   discarded on every failed request in the whole product.
E  Robot artwork in the landing empty state and the brand, hand-authored as
   inline SVG because this machine has no network access.

The art is confined to #map-placeholder, which index.html only shows until the
first state frame arrives, so it can never cover a live robot dot or a metric.
"""
import io
import os
import subprocess
import sys


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def save(path, text):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ------------------------------------------------------------------ A: NaN ---
p = "web/js/main.js"
t = load(p)
t = sub(
    t,
    '  set("kpi-verdicts", k.verdicts == null ? DASH : int(k.verdicts));',
    "  set(\"kpi-verdicts\", verdictTotal(k.verdicts));",
    "A verdicts call site",
)
t = sub(
    t,
    "function paintKpis() {",
    """/* kpis().verdicts is a nested map of kind -> count, not a scalar. Passing it
 * straight to int() produced NaN on screen for the whole run. Sum the counts,
 * and keep DASH for "no data" so a missing value is never drawn as a zero. */
function verdictTotal(verdicts) {
  if (verdicts == null) return DASH;
  if (typeof verdicts === "number") return int(verdicts);
  const counts = Object.values(verdicts).filter((v) => typeof v === "number");
  if (!counts.length) return DASH;
  return int(counts.reduce((a, b) => a + b, 0));
}

function paintKpis() {""",
    "A verdictTotal helper",
)
save(p, t)

# --------------------------------------------------------- D: error message ---
p = "web/js/transport.js"
t = load(p)
old = "        return { ok: false, error: (data && data.detail) || `HTTP ${res.status}`, data };"
new = "        return { ok: false, error: apiError(data, res.status), data };"
n = t.count(old)
assert n == 2, "D: expected 2 error sites, found %d" % n
t = t.replace(old, new)
t = sub(
    t,
    "  async post(path, body) {",
    """  /* The API reports a failure as {ok: false, error: "<human sentence>"}.
   * This used to read data.detail, which the server never sends, so every 4xx
   * in the product collapsed to a bare "HTTP 400" and threw away the one piece
   * of text that told the operator what to do about it. */
  async post(path, body) {""",
    "D post comment",
)
t = sub(
    t,
    "export class Transport",
    """function apiError(data, status) {
  if (data && typeof data.error === "string" && data.error) return data.error;
  if (data && typeof data.detail === "string" && data.detail) return data.detail;
  return `The server rejected the request (HTTP ${status}).`;
}

export class Transport""",
    "D apiError helper",
)
save(p, t)

# ------------------------------------------------- B and C: CSS class split ---
p = "web/styles/panels.css"
t = load(p)
t = sub(
    t,
    """.palette__hint {
  display: flex;""",
    """/* The footer hint bar. Distinct from .palette__key, which is the small
 * shortcut badge inside a row: one class cannot be both a full-width bar with
 * a top border and an inline badge, and when it tried, every badge in the
 * palette rendered as a full-width box. */
.palette__hint {
  display: flex;""",
    "B footer comment",
)
t = sub(
    t,
    """.chart__key {
  display: inline-block;
  width: 8px;
  height: 2px;
  margin-right: 4px;
  vertical-align: middle;
}""",
    """/* A legend entry is the wrapper; the swatch is the <i> inside it. These were
 * the same selector, which forced the text wrapper to 8x2 px and spilled the
 * "100 ms tick budget" label across the chart underneath. */
.chart__key {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}
.chart__key > i {
  display: inline-block;
  width: 8px;
  height: 2px;
  flex: 0 0 auto;
  vertical-align: middle;
}

/* Legend entries wrap instead of overflowing when a label is long. */
.chart__legend { flex-wrap: wrap; row-gap: 2px; }

/* The palette row badge. Inline, hugs its text, no border-top. */
.palette__key {
  justify-self: end;
  font-family: var(--font-mono);
  font-size: var(--text-micro);
  color: var(--ink-tertiary);
  background: var(--surface-2);
  border: 1px solid var(--line-default);
  border-radius: var(--radius-sm);
  padding: 1px 5px;
  white-space: nowrap;
}

/* ------------------------------------------- robot artwork (landing only) ---
 * Hand-authored inline SVG: this build has no network access, so no raster
 * asset can be fetched, and vector art stays crisp on any projector. It lives
 * only inside #map-placeholder, which is removed as soon as the first state
 * frame lands, so it cannot overlap live robots or telemetry. Decoration never
 * takes pointer events and never sits above the canvases. */
.hero {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-6, 32px);
  pointer-events: none;
}
.hero__art {
  flex: 0 0 auto;
  width: 300px;
  max-width: 34vw;
  height: auto;
  color: var(--ink-tertiary);
  pointer-events: none;
}
.hero__copy { position: relative; z-index: 1; text-align: left; }
.hero__copy > * { pointer-events: auto; }

/* One slow sweep of the sensing arc, on the landing screen only. */
.hero__sweep {
  transform-origin: 96px 96px;
  animation: hero-sweep 3.2s linear infinite;
}
@keyframes hero-sweep { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .hero__sweep { animation: none; }
}
@media (max-width: 1100px) {
  .hero__art { display: none; }
}

/* Brand glyph beside the SWARMOS wordmark, so the robotics read survives
 * after the landing hero is gone. */
.brand__glyph {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  margin-right: 8px;
  color: var(--ink-secondary);
  pointer-events: none;
}""",
    "C chart__key split",
)
save(p, t)

# ------------------------------------------------------- B: palette markup ---
p = "web/js/palette.js"
t = load(p)
t = sub(
    t,
    '${c.hint ? `<span class="palette__hint kbd">${c.hint}</span>` : ""}',
    '${c.hint ? `<span class="palette__key">${c.hint}</span>` : ""}',
    "B palette row badge",
)
save(p, t)

# ------------------------------------------------------------- E: robot art ---
AMR = """        <svg class="hero__art" viewBox="0 0 192 192" fill="none"
             aria-hidden="true" focusable="false">
          <!-- Warehouse floor grid. Deliberately an AMR mobile base, not a
               humanoid: it is what the simulation actually models. -->
          <g stroke="currentColor" stroke-width="0.5" opacity="0.18">
            <path d="M12 36h168M12 72h168M12 108h168M12 144h168"/>
            <path d="M36 12v168M72 12v168M108 12v168M144 12v168"/>
          </g>
          <!-- Comm range, R_comm = 15 m -->
          <circle cx="96" cy="96" r="78" stroke="currentColor"
                  stroke-width="0.75" stroke-dasharray="3 6" opacity="0.4"/>
          <g class="hero__sweep" opacity="0.55">
            <path d="M96 96 L96 18" stroke="var(--state-sovereign)"
                  stroke-width="1"/>
            <path d="M96 18 A78 78 0 0 1 151 41" stroke="var(--state-sovereign)"
                  stroke-width="1.5" fill="none"/>
          </g>
          <!-- Load deck -->
          <path d="M54 92 L96 72 L138 92 L96 112 Z" stroke="currentColor"
                stroke-width="1.25" opacity="0.85"/>
          <path d="M54 92 L54 104 L96 124 L138 104 L138 92" stroke="currentColor"
                stroke-width="1.25" opacity="0.6"/>
          <path d="M96 112 L96 124" stroke="currentColor" stroke-width="1"
                opacity="0.6"/>
          <!-- Payload tote -->
          <path d="M74 82 L96 71 L118 82 L96 93 Z" stroke="currentColor"
                stroke-width="1" opacity="0.5"/>
          <!-- Lidar puck, drawn in SOVEREIGN teal: the one saturated accent -->
          <circle cx="96" cy="66" r="4.5" stroke="var(--state-sovereign)"
                  stroke-width="1.25"/>
          <circle cx="96" cy="66" r="1.5" fill="var(--state-sovereign)"
                  opacity="0.8"/>
          <!-- Wheels -->
          <path d="M62 106 L62 114M130 106 L130 114" stroke="currentColor"
                stroke-width="2" opacity="0.7"/>
          <!-- Peer robots, at the 4 px LOD dot size the map uses when zoomed out -->
          <circle cx="30" cy="150" r="2" fill="currentColor" opacity="0.55"/>
          <circle cx="160" cy="140" r="2" fill="currentColor" opacity="0.55"/>
          <circle cx="150" cy="160" r="2" fill="currentColor" opacity="0.4"/>
          <circle cx="40" cy="36" r="2" fill="currentColor" opacity="0.4"/>
        </svg>
"""

GLYPH = """      <svg class="brand__glyph" viewBox="0 0 24 24" fill="none"
           aria-hidden="true" focusable="false">
        <path d="M5 13 L12 9 L19 13 L12 17 Z" stroke="currentColor"
              stroke-width="1.5"/>
        <circle cx="12" cy="5.5" r="1.75" stroke="currentColor"
                stroke-width="1.5"/>
        <path d="M12 7.25 L12 9" stroke="currentColor" stroke-width="1.5"/>
      </svg>
"""

p = "web/index.html"
t = load(p)
t = sub(t, '      <span class="brand__mark">SWARMOS</span>',
        GLYPH + '      <span class="brand__mark">SWARMOS</span>', "E brand glyph")
t = sub(
    t,
    """      <div class="empty">
        <div class="empty__cause">No run has been started yet.</div>""",
    """      <div class="empty hero">
""" + AMR + """        <div class="hero__copy">
        <div class="empty__cause">No run has been started yet.</div>""",
    "E hero open",
)
t = sub(
    t,
    """        <div class="empty__hint">rush_50 &middot; seed 11 &middot; fleet 8</div>
      </div>""",
    """        <div class="empty__hint">rush_50 &middot; seed 11 &middot; fleet 8</div>
        </div>
      </div>""",
    "E hero close",
)
save(p, t)

# ------------------------------------------------------------------ gates ---
for js in ("web/js/main.js", "web/js/transport.js", "web/js/palette.js"):
    r = subprocess.run(["node", "--check", js], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("node --check FAILED for %s\n%s\n" % (js, r.stderr))
        sys.exit(1)
    print("node --check ok :", js)

for f in ("web/index.html", "web/styles/panels.css"):
    txt = load(f)
    bad = [c for c in txt if ord(c) > 127]
    print("%-24s %6d bytes  non-ascii=%d" % (f, len(txt), len(bad)))

print("open/close div balance in index.html:",
      load("web/index.html").count("<div"), load("web/index.html").count("</div>"))
print("ALL PATCHES APPLIED")
