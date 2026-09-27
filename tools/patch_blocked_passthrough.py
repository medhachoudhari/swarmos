"""Expose the blocked-cell footprint to the renderer.

The restricted-region drawing added for section 18 reads wh.blocked. The render
payload did not carry it, so that block was dead code. Warehouse.blocked
already exists and is already maintained by block_aisle_segment() and
clear_blockage(); this only forwards it for DRAWING.

Additive: one new key on an existing render payload, plus a passthrough in the
frontend normaliser. No existing key changes name, type or meaning, so no
existing consumer is affected. No simulation, planner or coordination logic is
touched - the blockage itself is produced by the unchanged BLOCK_AISLE fault.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


pending = {}

p = ROOT / "app" / "sim" / "warehouse.py"
src = p.read_text()
src = sub(
    src,
    """            "rack_spans": spans,
            "chargers": self.cells_of_type(Cell.CHARGER),""",
    """            "rack_spans": spans,
            # Blocked cells are forwarded so the map can draw the restricted
            # region. Sorted for a stable wire order, which keeps the payload
            # byte-identical across runs with the same blockage and therefore
            # keeps determinism receipts comparable.
            "blocked": sorted(self.blocked),
            "chargers": self.cells_of_type(Cell.CHARGER),""",
    "warehouse: forward blocked cells",
)
pending[p] = src
print("warehouse.py   : blocked cells forwarded to the render payload")

p = ROOT / "web" / "js" / "store.js"
src = p.read_text()
src = sub(
    src,
    """  return {
    width_m: wCells * cell,
    height_m: hCells * cell,
    cell_m: cell,
    racks,
    docks,
    zones,
  };""",
    """  // Blocked cells stay in CELL coordinates: the renderer multiplies by
  // cell_m itself when hatching them, because a blockage is a whole-cell fact
  // and rounding it into metres early would let it drift off the grid.
  const blocked = Array.isArray(wh.blocked)
    ? wh.blocked.filter((b) => Array.isArray(b) && b.length >= 2)
    : [];

  return {
    width_m: wCells * cell,
    height_m: hCells * cell,
    cell_m: cell,
    racks,
    docks,
    zones,
    blocked,
  };""",
    "store: pass blocked through",
)
pending[p] = src
print("store.js       : blocked cells passed through the normaliser")

for path, text in pending.items():
    path.write_text(text)
print("\nwrote %d file(s)" % len(pending))
