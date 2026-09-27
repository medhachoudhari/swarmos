"""Defect N: the warehouse static layer never rendered.

Root cause. store.js:137 assigned the websocket hello payload to
store.warehouse verbatim, with no normalisation. map.js then read four keys
that payload never contained:

    map.js reads        payload actually sends
    wh.width_m          width   (cells)
    wh.height_m         height  (cells)
    wh.racks            rack_spans  (run-length [x, y, run])
    wh.docks            chargers / pick / drop

Every one of those resolved to undefined, so fit() returned early, the floor
and grid were never painted, and the rack and dock loops never entered. The
warehouse the whole product is about was invisible. Nothing in the repo emitted
width_m, racks or docks, and no test asserted the render payload, which is why
575 green tests never caught it.

Fix. Normalise once, in the store, at the single point the payload enters the
frontend. The renderer keeps its existing metre-based vocabulary, the backend
keeps its existing compact cell-based wire format, and neither has to learn
about the other. Run-length rack spans are expanded to [x, y, w, h] metre
rectangles, and the three station families are merged into one dock list that
carries its own kind so the renderer can style each honestly.

This touches rendering only. No simulation, coordination, planner, API or
data-contract code is modified.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


pending = {}

# ---------------------------------------------------------------- store.js --
p = ROOT / "web" / "js" / "store.js"
src = p.read_text()

src = sub(
    src,
    """  /** Geometry + scenario identity. Sent once per run, not per tick. */
  applyHello(msg) {
    this.warehouse = msg.warehouse || null;""",
    """  /** Geometry + scenario identity. Sent once per run, not per tick. */
  applyHello(msg) {
    this.warehouse = normaliseWarehouse(msg.warehouse);""",
    "store.applyHello",
)

NORMALISER = '''
/* ------------------------------------------------------ warehouse payload --
 * The backend sends compact CELL geometry, because a 60x40 warehouse as
 * run-length spans is a few hundred bytes instead of 2400 cells. The renderer
 * works in METRES, because every other quantity in the product does. This is
 * the one place those two vocabularies meet.
 *
 * Wire format                      Renderer format
 *   width, height   (cells)          width_m, height_m   (metres)
 *   cell_m          (m per cell)     -- applied, not forwarded
 *   rack_spans      [x, y, run]      racks   [x, y, w, h] metre rects
 *   chargers/pick/drop [[x, y]]      docks   [x, y, kind] metre points
 *
 * Returns null for a missing or malformed payload, so the caller keeps its
 * honest "no warehouse yet" cold-start state rather than rendering a guess. */
function normaliseWarehouse(wh) {
  if (!wh) return null;

  const cell = typeof wh.cell_m === "number" && wh.cell_m > 0 ? wh.cell_m : 1.0;
  const wCells = Number(wh.width);
  const hCells = Number(wh.height);
  if (!Number.isFinite(wCells) || !Number.isFinite(hCells)) return null;
  if (wCells <= 0 || hCells <= 0) return null;

  // Run-length spans -> metre rectangles. A span is one cell tall by
  // construction, so height is always a single cell.
  const racks = [];
  if (Array.isArray(wh.rack_spans)) {
    for (const span of wh.rack_spans) {
      if (!Array.isArray(span) || span.length < 3) continue;
      const [cx, cy, run] = span;
      if (!(run > 0)) continue;
      racks.push([cx * cell, cy * cell, run * cell, cell]);
    }
  }

  // One dock list, each entry tagged with its kind, so the renderer can give
  // chargers, pick stations and drop stations distinct semantic styling
  // without three near-identical loops.
  const docks = [];
  const addDocks = (cells, kind) => {
    if (!Array.isArray(cells)) return;
    for (const c of cells) {
      if (!Array.isArray(c) || c.length < 2) continue;
      // +0.5 cell centres the marker in its cell rather than pinning it to
      // the corner, which is where a dock physically is.
      docks.push([(c[0] + 0.5) * cell, (c[1] + 0.5) * cell, kind]);
    }
  };
  addDocks(wh.chargers, "CHARGER");
  addDocks(wh.pick, "PICK");
  addDocks(wh.drop, "DROP");

  // Zones are advisory coordination regions (WEST / CENTRE / EAST), not
  // operational bays. Converted to metres and passed through under their real
  // names - the simulator models no inbound or outbound concept, so none is
  // invented here.
  const zones = [];
  if (Array.isArray(wh.zones)) {
    for (const z of wh.zones) {
      if (!z || typeof z.name !== "string") continue;
      zones.push({
        name: z.name,
        x0: z.x0 * cell,
        y0: z.y0 * cell,
        x1: (z.x1 + 1) * cell,
        y1: (z.y1 + 1) * cell,
      });
    }
  }

  return {
    width_m: wCells * cell,
    height_m: hCells * cell,
    cell_m: cell,
    racks,
    docks,
    zones,
  };
}

'''

src = sub(
    src,
    "class Store {",
    NORMALISER.lstrip("\n") + "class Store {",
    "store: insert normaliser before class",
)

pending[p] = src
print("store.js       : warehouse payload normaliser added")

for path, text in pending.items():
    path.write_text(text)
print("\nwrote %d file(s)" % len(pending))
