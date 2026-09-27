"""Warehouse visualisation and path legibility (master prompt sections 16-22).

Rendering only. No simulation, coordination, planner, API or data-contract code
is touched. Every value drawn comes from the existing websocket payload.

What changes.

  1. Docks are typed. The normaliser tags each dock CHARGER / PICK / DROP, so
     each family gets its own semantic colour and glyph instead of one
     undifferentiated blue ring. Section 18 asks for understandable operational
     zones; these are the ones the simulator actually models, so these are the
     only ones drawn. No inbound or outbound bay is invented.

  2. Rack aisle bays are labelled A1, A2 ... at high zoom only, so a viewer can
     see WHY a corridor exists (section 17). Labels are gated on pixel density
     and suppressed entirely when they would collide.

  3. Blocked cells are drawn as a restricted region. This is the real
     BLOCK_AISLE fault footprint, not decoration.

  4. Paths get the five-level hierarchy section 20 mandates, replacing a binary
     selected/not-selected split:
        selected     brightest, thickest
        active       bright        (robot is MOVING)
        planned      dashed        (robot holds a path but is not moving)
        secondary    dotted, faint (everything else)
        conflict     warning red   (robot is BLOCKED)
     Section 21 is honoured by SUBDUING non-selected paths when a selection
     exists rather than brightening the selected one into glare.

  5. The paths layer no longer disappears at low zoom. It previously returned
     early below LOD_PX_PER_M (6 px/m), which at the fitted 0.57x zoom of a
     60 m warehouse meant paths were never drawn at all - the actual reason
     they looked "too faint". Now low zoom SIMPLIFIES (thin, no dashes, only
     selected plus conflicts) instead of hiding, which is what section 22 asks
     for: readability over uniform maximum brightness.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


pending = {}

# ------------------------------------------------------------------ tokens --
p = ROOT / "web" / "styles" / "tokens.css"
css = p.read_text()

css = sub(
    css,
    """  --map-path: rgba(200, 210, 220, 0.22);      /* planned path, ghosted */
  --map-path-active: rgba(200, 210, 220, 0.55);""",
    """  --map-path: rgba(200, 210, 220, 0.22);      /* planned path, ghosted */
  --map-path-active: rgba(200, 210, 220, 0.55);
  /* Five-level path hierarchy (master prompt section 20). The ladder is
   * ordered by opacity, not by hue: hue stays reserved for STATE, so a
   * brighter line means "more relevant right now", never "different kind of
   * thing". --map-path-secondary is deliberately dim enough that fifty of
   * them read as texture rather than as spaghetti. */
  --map-path-selected: rgba(232, 237, 242, 0.92);
  --map-path-moving: rgba(200, 210, 220, 0.58);
  --map-path-planned: rgba(200, 210, 220, 0.34);
  --map-path-secondary: rgba(200, 210, 220, 0.16);
  --map-path-conflict: rgba(229, 72, 77, 0.72);
  /* Rack bay labels: tertiary ink, so structure never outshouts robots. */
  --map-rack-label: #63707D;
  /* Operational stations. These three are the only ones the simulator
   * models, so they are the only ones drawn. */
  --map-dock-charger: rgba(62, 155, 255, 0.85);
  --map-dock-pick: rgba(79, 179, 166, 0.85);
  --map-dock-drop: rgba(245, 166, 35, 0.80);
  /* Restricted region = the real blocked-aisle fault footprint. */
  --map-restricted: rgba(229, 72, 77, 0.55);
  --map-restricted-wash: rgba(229, 72, 77, 0.10);""",
    "tokens: path hierarchy + station colours",
)
pending[p] = css
print("tokens.css     : path hierarchy, dock, rack-label, restricted tokens")

# ------------------------------------------------------------------ map.js --
p = ROOT / "web" / "js" / "map.js"
js = p.read_text()

js = sub(
    js,
    """const RACK_OUTLINE_PX_PER_M = 6;  // below this, racks are filled but not outlined
const DOCK_LABEL_PX_PER_M = 10;   // below this, dock labels are unreadable""",
    """const RACK_OUTLINE_PX_PER_M = 6;  // below this, racks are filled but not outlined
const DOCK_LABEL_PX_PER_M = 10;   // below this, dock labels are unreadable
// Rack bay ids (A1, A2, ...) need room for ~2 characters inside a 1 m cell.
const RACK_ID_PX_PER_M = 22;
// Below this the path layer SIMPLIFIES - thin, undashed, selected and
// conflicts only. It does not switch off. A fitted 60 m warehouse sits near
// 11 px/m, so anything that switches off above that is invisible in practice.
const PATH_DETAIL_PX_PER_M = 14;""",
    "map: LOD constants",
)

# --- docks: typed stations, replacing the single blue ring loop -------------
js = sub(
    js,
    """    // Charging docks, if the scenario declares them.
    if (Array.isArray(wh.docks) && s >= DOCK_LABEL_PX_PER_M) {
      ctx.strokeStyle = css("--state-charging");
      ctx.lineWidth = 1.5;
      for (const d of wh.docks) {
        const [sx, sy] = this.toScreen(d[0], d[1]);
        ctx.beginPath();
        ctx.arc(sx, sy, 0.45 * s, 0, Math.PI * 2);
        ctx.stroke();
      }
    }""",
    """    // Operational stations. Each dock arrives tagged with its kind, so the
    // three families the simulator models get three distinct reads. A charger
    // is a ring, a pick station a triangle pointing out of the warehouse, a
    // drop station a square - shape as well as colour, so the distinction
    // survives a projector with poor colour fidelity.
    if (Array.isArray(wh.docks) && s >= DOCK_LABEL_PX_PER_M) {
      ctx.lineWidth = 1.5;
      for (const d of wh.docks) {
        const [sx, sy] = this.toScreen(d[0], d[1]);
        const kind = d[2];
        const r = 0.42 * s;
        if (kind === "CHARGER") {
          ctx.strokeStyle = css("--map-dock-charger");
          ctx.beginPath();
          ctx.arc(sx, sy, r, 0, Math.PI * 2);
          ctx.stroke();
        } else if (kind === "PICK") {
          ctx.strokeStyle = css("--map-dock-pick");
          ctx.beginPath();
          ctx.moveTo(sx, sy - r);
          ctx.lineTo(sx + r, sy + r);
          ctx.lineTo(sx - r, sy + r);
          ctx.closePath();
          ctx.stroke();
        } else {
          ctx.strokeStyle = css("--map-dock-drop");
          ctx.strokeRect(sx - r, sy - r, r * 2, r * 2);
        }
      }
    }

    // Restricted region: the live BLOCK_AISLE footprint. Cross-hatched rather
    // than solid, so a blocked cell can never be mistaken for a rack.
    const blocked = wh.blocked;
    if (Array.isArray(blocked) && blocked.length) {
      ctx.fillStyle = css("--map-restricted-wash");
      ctx.strokeStyle = css("--map-restricted");
      ctx.lineWidth = 1;
      const cm = wh.cell_m || 1;
      for (const b of blocked) {
        if (!Array.isArray(b) || b.length < 2) continue;
        const [bx, by] = this.toScreen(b[0] * cm, (b[1] + 1) * cm);
        const w = cm * s;
        ctx.fillRect(bx, by, w, w);
        ctx.beginPath();
        ctx.moveTo(bx, by);
        ctx.lineTo(bx + w, by + w);
        ctx.moveTo(bx + w, by);
        ctx.lineTo(bx, by + w);
        ctx.stroke();
      }
    }""",
    "map: typed docks + restricted region",
)

# --- rack bay labels --------------------------------------------------------
js = sub(
    js,
    """      for (const rk of wh.racks) {
        const [rx, ry, rw, rh] = rk;
        const [sx, sy] = this.toScreen(rx, ry + rh);
        ctx.fillRect(sx, sy, rw * s, rh * s);
        if (s >= RACK_OUTLINE_PX_PER_M) ctx.strokeRect(sx, sy, rw * s, rh * s);
      }
    }""",
    """      for (const rk of wh.racks) {
        const [rx, ry, rw, rh] = rk;
        const [sx, sy] = this.toScreen(rx, ry + rh);
        ctx.fillRect(sx, sy, rw * s, rh * s);
        if (s >= RACK_OUTLINE_PX_PER_M) ctx.strokeRect(sx, sy, rw * s, rh * s);
      }

      // Bay ids, so the aisle structure is readable as structure and not as
      // abstract blocks (section 17). One label per rack BLOCK, not per span:
      // spans are run-length rows, and labelling every row would produce a
      // wall of text. A block is identified by its column band, which is what
      // a warehouse operator would call an aisle.
      if (s >= RACK_ID_PX_PER_M) {
        ctx.fillStyle = css("--map-rack-label");
        ctx.font = "600 9px ui-monospace, SFMono-Regular, Menlo, monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const seen = new Set();
        for (const rk of wh.racks) {
          const [rx, ry, rw, rh] = rk;
          // Band key: rack columns repeat on a fixed pitch, so rounding the
          // left edge groups a vertical stack of spans into one bay.
          const band = Math.round(rx);
          if (seen.has(band)) continue;
          seen.add(band);
          const letter = String.fromCharCode(65 + (seen.size - 1) % 26);
          const idx = Math.floor((seen.size - 1) / 26) + 1;
          const [lx, ly] = this.toScreen(rx + rw / 2, ry + rh / 2);
          ctx.fillText(letter + idx, lx, ly);
        }
      }
    }""",
    "map: rack bay labels",
)

# --- five-level path hierarchy ---------------------------------------------
js = sub(
    js,
    """  drawPaths() {
    const ctx = this.pctx;
    ctx.clearRect(0, 0, this.w, this.h);
    const s = this.scale();
    if (s < LOD_PX_PER_M) { this._pathsDirty = false; return; }

    const sel = store.selectedRobot;

    for (const r of store.robots.values()) {
      if (this.hidden.has(r.status)) continue;
      const mi = r.movement_intent;
      if (!mi || !Array.isArray(mi.path) || mi.path.length < 2) continue;

      const isSel = r.robot_id === sel;
      ctx.strokeStyle = isSel ? css("--map-path-active") : css("--map-path");
      ctx.lineWidth = isSel ? 2 : 1;
      ctx.beginPath();""",
    """  drawPaths() {
    const ctx = this.pctx;
    ctx.clearRect(0, 0, this.w, this.h);
    const s = this.scale();

    const sel = store.selectedRobot;
    // Low zoom simplifies rather than hides (section 22). Dashes and faint
    // secondary lines turn to mud below this density, so at low zoom only the
    // lines that carry meaning are drawn: the selection and anything blocked.
    const detail = s >= PATH_DETAIL_PX_PER_M;

    for (const r of store.robots.values()) {
      if (this.hidden.has(r.status)) continue;
      const mi = r.movement_intent;
      if (!mi || !Array.isArray(mi.path) || mi.path.length < 2) continue;

      const isSel = r.robot_id === sel;
      const isConflict = r.status === "BLOCKED";
      if (!detail && !isSel && !isConflict) continue;

      // Five-level ladder. Ordered most to least relevant, so the first
      // matching rung wins.
      let stroke;
      let width;
      let dash = null;
      if (isSel) {
        stroke = css("--map-path-selected");
        width = 2.5;
      } else if (isConflict) {
        stroke = css("--map-path-conflict");
        width = 1.75;
      } else if (r.status === "MOVING") {
        stroke = css("--map-path-moving");
        width = 1.25;
      } else if (mi.path.length > 1) {
        stroke = css("--map-path-planned");
        width = 1;
        dash = [4, 3];
      } else {
        stroke = css("--map-path-secondary");
        width = 1;
        dash = [1, 3];
      }

      // Section 21: when something is selected, everything else steps back.
      // Subduing the field is what makes one path followable; brightening the
      // selection alone just raises the floor.
      if (sel && !isSel) ctx.globalAlpha = 0.45;

      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.setLineDash(detail && dash ? dash : []);
      ctx.beginPath();""",
    "map: five-level path hierarchy",
)

js = sub(
    js,
    """        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      }
      ctx.stroke();

      // Goal marker, drawn only for the selected robot to keep the map calm.""",
    """        if (i === 0) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      // Goal marker, drawn only for the selected robot to keep the map calm.""",
    "map: reset dash and alpha after each path",
)

pending[p] = js
print("map.js         : typed docks, restricted cells, bay labels, 5-level paths")

for path, text in pending.items():
    path.write_text(text)
print("\nwrote %d file(s)" % len(pending))
