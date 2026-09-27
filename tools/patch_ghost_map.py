"""Add a baseline ghost layer to web/js/map.js.

The ghosts are the baseline arm of an X-12 co-simulation. They are drawn
BEFORE the live fleet so they always sit behind it, and they are drawn in ink
only - never in state colour - because state colour is reserved for robots that
actually exist. A hypothesis that looks like a robot is a lie.
"""
import subprocess
import sys

PATH = "web/js/map.js"


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected 1 match, found {n}"
    return text.replace(old, new)


text = open(PATH).read()

# 1. Constants for the ghost layer.
text = sub(
    text,
    'const TRAIL_MAX = 120;            // 12 s of trail for the selected robot\n',
    'const TRAIL_MAX = 120;            // 12 s of trail for the selected robot\n'
    'const GHOST_ALPHA = 0.30;         // baseline arm: present but never competing\n',
    "constants",
)

# 2. Ghost source hook on the instance.
text = sub(
    text,
    '    this.pulses = new Map();          // conflictId -> started-at ms\n',
    '    this.pulses = new Map();          // conflictId -> started-at ms\n'
    '\n'
    '    /* Baseline ghost overlay (X-12). A function returning\n'
    '     * {robots, at} or null. Null means draw nothing, which is what an\n'
    '     * unstarted or non-comparable co-simulation must look like. */\n'
    '    this.ghostSource = null;\n',
    "ghost source field",
)

# 3. The ghost painter, inserted just before drawRobots.
ghost_method = '''  /* Baseline ghosts (X-12). Drawn FIRST so the real fleet is always on top,
   * and drawn in tertiary ink at low alpha so they read as "the other world"
   * rather than as robots. No state colour, no labels, no selection ring: the
   * ghosts are context, not subjects. */
  _drawGhosts(ctx, now, s) {
    if (!this.ghostSource) return;
    const src = this.ghostSource();
    if (!src || !src.robots || !src.robots.length) return;

    const age = now - (src.at || 0);
    const t = Math.max(0, Math.min(1, age / TICK_MS));
    const lod = this.zoom < LOD_ZOOM;
    const rpx = Math.max(2, ROBOT_RADIUS_M * s);

    ctx.save();
    ctx.globalAlpha = GHOST_ALPHA;
    ctx.strokeStyle = css("--ink-tertiary");
    ctx.fillStyle = css("--ink-tertiary");
    ctx.lineWidth = 1;

    for (const r of src.robots) {
      const prev = r.prevPosition || r.position;
      const ix = prev.x + (r.position.x - prev.x) * t;
      const iy = prev.y + (r.position.y - prev.y) * t;
      const [sx, sy] = this.toScreen(ix, iy);
      if (sx < -20 || sy < -20 || sx > this.w + 20 || sy > this.h + 20) continue;

      ctx.beginPath();
      ctx.arc(sx, sy, lod ? 2 : rpx, 0, Math.PI * 2);
      if (lod) ctx.fill();
      else ctx.stroke();
    }

    ctx.restore();
  }

'''
text = sub(
    text,
    '  drawRobots(now) {\n',
    ghost_method + '  drawRobots(now) {\n',
    "ghost method",
)

# 4. Call it at the top of the robots layer, after the clear.
text = sub(
    text,
    '    const s = this.scale();\n'
    '    const lod = this.zoom < LOD_ZOOM;\n',
    '    const s = this.scale();\n'
    '    const lod = this.zoom < LOD_ZOOM;\n'
    '\n'
    '    // Ghosts first: the counterfactual never occludes the real fleet.\n'
    '    this._drawGhosts(ctx, now, s);\n',
    "ghost call",
)

open(PATH, "w").write(text)
r = subprocess.run(["node", "--check", PATH], capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write(r.stdout + r.stderr)
    raise SystemExit("node --check failed")
print("map.js ghost layer OK")
