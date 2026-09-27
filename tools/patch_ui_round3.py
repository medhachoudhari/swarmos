"""UI round 3. Fixes five defects found from the user's 8 screenshots.

I  lab.js   scenario <option value> was "[object Object]" because the
            fallback chain "s.id || s" fell back to the whole record.
            ScenarioSpec.as_dict() emits "name", never "id".
J  map.js   grid was invisible: px-per-metre thresholds excluded the fitted
            scale, and the grid tokens sat only a few RGB steps above the
            floor. Thresholds lowered and tokens.css grid colours lightened,
            still kept below --line-default so the grid never out-inks data.
K  map.js   LOD collapsed the fleet to bare dots after Fit because the
            threshold compared this.zoom (a relative multiplier) when the
            thing being regulated is absolute pixel density. Re-expressed in
            px per metre, i.e. against this.scale().
L  main.js  palette advertised keys 0 / R that were never bound globally.
            Bound them, with a guard so they never fire while a text field,
            select or the palette itself has focus.
M  transport.js the stale banner latched on forever: it was cleared only
            when link was still DEGRADED, but an arriving frame sets link
            back to LIVE first, making the clear branch unreachable.
            Ownership flag added so the watch clears its own banner only.

All edits are applied in memory; every file is saved only after all the
asserts pass, so a partial failure leaves the tree untouched.
"""
import ast
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


def load(rel):
    with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def save(rel, text):
    with io.open(os.path.join(ROOT, rel), "w", encoding="utf-8") as fh:
        fh.write(text)


pending = {}

# ---------------------------------------------------------------- I : lab.js
LAB = "web/js/panels/lab.js"
lab = load(LAB)
lab = sub(
    lab,
    '      ? this.scenarios.map((s) => `<option value="${s.id || s}">${s.name || s.id || s}</option>`).join("")',
    "      // The server key is ScenarioSpec.as_dict().name. There is no 'id'\n"
    "      // field, so a fallback must land on another FIELD, never on the\n"
    "      // whole record - that is what produced value=\"[object Object]\".\n"
    '      ? this.scenarios.map((s) => `<option value="${s.name}">${s.title || s.name}</option>`).join("")',
    "I lab option value",
)
pending[LAB] = lab

# ------------------------------------------------------------- J + K : map.js
MAP = "web/js/map.js"
mp = load(MAP)
mp = sub(
    mp,
    "const LOD_ZOOM = 0.6;             // below this, robots are plain dots\n"
    "const LABEL_ZOOM = 1.1;           // below this, no per-robot id labels",
    "// Level of detail is a function of PIXEL DENSITY, not of the relative\n"
    "// zoom multiplier: scale() = fitScale * zoom is what the eye actually\n"
    "// sees. A fitted 60 m warehouse can sit at zoom 0.58 and still have\n"
    "// plenty of pixels per metre.\n"
    "const LOD_PX_PER_M = 6;           // below this, robots are plain dots\n"
    "const LABEL_PX_PER_M = 26;        // below this, no per-robot id labels\n"
    "const GRID_PX_PER_M = 4;          // below this, no grid at all\n"
    "const GRID_MINOR_PX_PER_M = 10;   // below this, major lines only",
    "K thresholds",
)
mp = sub(
    mp,
    "    // Grid at the 1 m aisle pitch, with a major line every 5 m. Below 8 px per\n"
    "    // metre the minor grid becomes moire, so it is dropped.\n"
    "    if (s >= 8) {",
    "    // Grid at the 1 m aisle pitch, with a major line every 5 m. Below\n"
    "    // GRID_MINOR_PX_PER_M the minor grid becomes moire, so only the 5 m\n"
    "    // majors are drawn; below GRID_PX_PER_M the grid is dropped entirely.\n"
    "    if (s >= GRID_PX_PER_M) {",
    "J grid gate",
)
mp = sub(
    mp,
    "        const major = gx % 5 === 0;\n        if (!major && s < 14) continue;",
    "        const major = gx % 5 === 0;\n        if (!major && s < GRID_MINOR_PX_PER_M) continue;",
    "J grid minor x",
)
mp = sub(
    mp,
    "        const major = gy % 5 === 0;\n        if (!major && s < 14) continue;",
    "        const major = gy % 5 === 0;\n        if (!major && s < GRID_MINOR_PX_PER_M) continue;",
    "J grid minor y",
)
mp = sub(
    mp,
    "    if (this.zoom < LOD_ZOOM) { this._pathsDirty = false; return; }",
    "    if (s < LOD_PX_PER_M) { this._pathsDirty = false; return; }",
    "K paths lod",
)
mp = sub(
    mp,
    "    const lod = this.zoom < LOD_ZOOM;\n    const rpx = Math.max(2, ROBOT_RADIUS_M * s);",
    "    const lod = s < LOD_PX_PER_M;\n    const rpx = Math.max(2, ROBOT_RADIUS_M * s);",
    "K ghost lod",
)
mp = sub(
    mp,
    "    const lod = this.zoom < LOD_ZOOM;\n\n    // Ghosts first",
    "    const lod = s < LOD_PX_PER_M;\n\n    // Ghosts first",
    "K robots lod",
)
mp = sub(
    mp,
    "      if (this.zoom >= LABEL_ZOOM) {",
    "      if (s >= LABEL_PX_PER_M) {",
    "K label gate",
)
pending[MAP] = mp

# ------------------------------------------------------------- J : tokens.css
TOK = "web/styles/tokens.css"
tok = load(TOK)
tok = sub(
    tok,
    "  --map-grid: #161D25;\n  --map-grid-major: #1E2831;",
    "  /* Readable against --map-floor yet still quieter than --line-default\n"
    "     (#263039), so the grid orients the eye without competing with the\n"
    "     data ink. */\n"
    "  --map-grid: #1E2832;\n  --map-grid-major: #2E3B47;",
    "J tokens",
)
pending[TOK] = tok

# ------------------------------------------------------------- L : main.js
MAIN = "web/js/main.js"
mn = load(MAIN)
mn = sub(
    mn,
    '    { name: "Start run", desc: "Start the configured scenario", hint: "Lab",',
    '    { name: "Start run", desc: "Start the configured scenario",',
    "L drop Lab hint",
)
# The palette instance was thrown away, so nothing could ask whether it is
# open. Keep a handle on it - the global key handler must not fire while the
# palette owns the keyboard.
mn = sub(
    mn,
    "new Palette({\n  scrim:",
    "const palette = new Palette({\n  scrim:",
    "L palette handle",
)
mn = sub(
    mn,
    'document.addEventListener("keydown", (e) => {\n'
    '  if (e.key === "Escape" && store.selectedRobot) store.select(null);\n'
    "});",
    "/* Global shortcuts. Every key advertised in the command palette or in a\n"
    " * banner action string must be bound here, otherwise the UI promises\n"
    " * something it does not do. A key is swallowed while the user is typing\n"
    " * in a field, while a modifier is held, or while the palette is open. */\n"
    "function typingTarget(t) {\n"
    "  if (!t || !t.tagName) return false;\n"
    '  const tag = t.tagName.toLowerCase();\n'
    '  if (tag === "input" || tag === "select" || tag === "textarea") return true;\n'
    "  return t.isContentEditable === true;\n"
    "}\n"
    "\n"
    'document.addEventListener("keydown", (e) => {\n'
    '  if (e.key === "Escape") {\n'
    "    if (store.selectedRobot) store.select(null);\n"
    "    return;\n"
    "  }\n"
    "  if (e.ctrlKey || e.metaKey || e.altKey) return;\n"
    "  if (typingTarget(e.target)) return;\n"
    "  if (palette && palette.open) return;\n"
    "\n"
    '  if (e.key === "0") {\n'
    "    e.preventDefault();\n"
    "    map.fit();\n"
    "    paintMapInfo();\n"
    '  } else if (e.key === "r" || e.key === "R") {\n'
    "    e.preventDefault();\n"
    "    transport.retryNow();\n"
    "  }\n"
    "});",
    "L global keys",
)
pending[MAIN] = mn

# ---------------------------------------------------------- M : transport.js
TRN = "web/js/transport.js"
tr = load(TRN)
tr = sub(
    tr,
    "      if (age > STALE_MS && store.link === LINK.LIVE) {\n"
    "        store.setLink(LINK.DEGRADED, `${Math.round(age)} ms since last frame`);\n"
    "        this.onBanner({\n"
    "          tone: \"warn\",\n"
    "          cause: `No simulation frame for ${Math.round(age)} ms (expected every 100 ms).`,\n"
    "          action: \"The map is showing the last known state. Coordination may be paused.\",\n"
    "        });\n"
    "      } else if (age <= STALE_MS && store.link === LINK.DEGRADED) {\n"
    "        store.setLink(LINK.LIVE);\n"
    "        this.onBanner(null);\n"
    "      }",
    "      if (age > STALE_MS) {\n"
    "        if (store.link === LINK.LIVE) {\n"
    "          store.setLink(LINK.DEGRADED, `${Math.round(age)} ms since last frame`);\n"
    "        }\n"
    "        if (store.link === LINK.DEGRADED) {\n"
    "          this._staleBannerOn = true;\n"
    "          this.onBanner({\n"
    "            tone: \"warn\",\n"
    "            cause: `No simulation frame for ${Math.round(age)} ms (expected every 100 ms).`,\n"
    "            action: \"The map is showing the last known state. Coordination may be paused.\",\n"
    "          });\n"
    "        }\n"
    "      } else {\n"
    "        // Frames are flowing again. applyFrame() may already have set the\n"
    "        // link back to LIVE, so the clear must NOT be gated on DEGRADED or\n"
    "        // it becomes unreachable and the banner latches on forever. The\n"
    "        // ownership flag keeps us from clearing somebody else's banner\n"
    "        // (a socket-closed or server-error banner must survive).\n"
    "        if (store.link === LINK.DEGRADED) store.setLink(LINK.LIVE);\n"
    "        if (this._staleBannerOn) {\n"
    "          this._staleBannerOn = false;\n"
    "          this.onBanner(null);\n"
    "        }\n"
    "      }",
    "M stale banner clear",
)
tr = sub(
    tr,
    "  _stopStaleWatch() {\n    if (this._staleTimer) clearInterval(this._staleTimer);\n    this._staleTimer = null;\n  }",
    "  _stopStaleWatch() {\n"
    "    if (this._staleTimer) clearInterval(this._staleTimer);\n"
    "    this._staleTimer = null;\n"
    "    this._staleBannerOn = false;\n"
    "  }",
    "M stale flag reset",
)
pending[TRN] = tr

# ---------------------------------------------------------------- save all
for rel, text in pending.items():
    save(rel, text)
    print("wrote %s" % rel)
print("round 3 patch applied to %d files" % len(pending))
