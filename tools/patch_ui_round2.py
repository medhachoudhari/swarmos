"""Fix the three defects the second screenshot round exposed.

F  Command palette rows: the shortcut badge still rendered as a full-width box
   on its own line. The earlier fix gave the badge its own class, which was
   necessary but not sufficient - the real cause is that .palette__item is a
   two-column grid with THREE children. Name lands in col 1, desc in col 2, and
   the badge wraps onto an implicit second row where col 1 is 1fr, i.e. full
   width. Fix the grid instead of the badge: name and desc stack in column 1,
   the badge occupies column 2 across both rows.

G  The state legend on the map rendered as a light grey panel on the dark
   theme. .legend__row is a <button>, and nothing in the rule reset the user
   agent's default ButtonFace background and border, so every row painted its
   own light chrome on top of the translucent dark panel.

H  The map read as near-empty black space. map.fit() early-returns when
   store.warehouse is null, and at startup it always is - the warehouse arrives
   later on the first websocket frame (store.js sets it) and nothing called
   fit() again. So fitScale was never computed from the real warehouse and the
   layout sat at a default that pushed most of the floor off-canvas. Fit once,
   the first time a warehouse becomes known.
"""
import io
import subprocess
import sys


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


def load(p):
    with io.open(p, encoding="utf-8") as fh:
        return fh.read()


def save(p, t):
    with io.open(p, "w", encoding="utf-8") as fh:
        fh.write(t)


# ------------------------------------------------------- F: palette grid ---
p = "web/styles/panels.css"
t = load(p)
t = sub(
    t,
    """.palette__item {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.palette__item[aria-selected="true"] { background: var(--surface-4); }
.palette__name { font-size: var(--text-body); color: var(--ink-primary); }
.palette__desc { font-size: var(--text-micro); color: var(--ink-tertiary); display: block; }""",
    """/* Three children, two columns. The name and the description stack in column
 * one and the shortcut badge sits in column two spanning both rows. Declaring
 * the areas explicitly is what stops the badge from wrapping onto an implicit
 * third row, where a 1fr column made it look like a full-width bar. */
.palette__item {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas:
    "name key"
    "desc key";
  align-items: center;
  column-gap: var(--space-3);
  row-gap: 1px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.palette__item[aria-selected="true"] { background: var(--surface-4); }
.palette__name {
  grid-area: name;
  font-size: var(--text-body);
  color: var(--ink-primary);
}
.palette__desc {
  grid-area: desc;
  font-size: var(--text-micro);
  color: var(--ink-tertiary);
}""",
    "F palette grid",
)
t = sub(
    t,
    """.palette__key {
  justify-self: end;""",
    """.palette__key {
  grid-area: key;
  align-self: center;
  justify-self: end;""",
    "F palette key area",
)

# --------------------------------------------------- G: legend button reset ---
t = sub(
    t,
    """.legend__row {
  display: flex;""",
    """/* Each row is a <button> so the state can be muted from the keyboard. Without
 * an explicit reset the user agent paints ButtonFace and a default border,
 * which turned the whole legend into a light grey panel on the dark theme. */
.legend__row {
  appearance: none;
  -webkit-appearance: none;
  background: none;
  border: 0;
  margin: 0;
  padding: 0;
  font: inherit;
  text-align: left;
  display: flex;""",
    "G legend button reset",
)
save(p, t)

# ------------------------------------------------- H: fit when warehouse lands ---
p = "web/js/map.js"
t = load(p)
t = sub(
    t,
    """  fit() {
    const wh = store.warehouse;
    if (!wh || !wh.width_m || !wh.height_m) return;""",
    """  /* Fit needs a warehouse, and at startup there is not one yet - it arrives on
   * the first state frame. Calling fit() before then is a no-op, so the very
   * first successful fit has to be triggered by the frame that brings the
   * warehouse in. See maybeFitOnFirstWarehouse(). */
  fit() {
    const wh = store.warehouse;
    if (!wh || !wh.width_m || !wh.height_m) return;
    this._hasFit = true;""",
    "H fit guard",
)
t = sub(
    t,
    """  zoomBy(factor, cx, cy) {""",
    """  /* Called every frame. Fits exactly once, when a warehouse first becomes
   * known, and never again - refitting later would yank the view out from under
   * an operator who has panned or zoomed deliberately. */
  maybeFitOnFirstWarehouse() {
    if (this._hasFit) return false;
    const wh = store.warehouse;
    if (!wh || !wh.width_m || !wh.height_m) return false;
    this.fit();
    return true;
  }

  zoomBy(factor, cx, cy) {""",
    "H maybeFit method",
)
t = sub(
    t,
    """      const now = performance.now();
      if (this._staticDirty) this.drawStatic();""",
    """      const now = performance.now();
      this.maybeFitOnFirstWarehouse();
      if (this._staticDirty) this.drawStatic();""",
    "H frame hook",
)
save(p, t)

# ------------------------------------------------------------------ gates ---
r = subprocess.run(["node", "--check", "web/js/map.js"], capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write("node --check FAILED\n%s\n" % r.stderr)
    sys.exit(1)
print("node --check ok : web/js/map.js")

css = load("web/styles/panels.css")
print("panels.css braces:", css.count("{"), css.count("}"))
print("non-ascii in panels.css:", len([c for c in css if ord(c) > 127]))
for need in ("grid-template-areas", "grid-area: key", "appearance: none"):
    assert need in css, "missing %s" % need
mj = load("web/js/map.js")
for need in ("maybeFitOnFirstWarehouse", "this._hasFit = true"):
    assert need in mj, "missing %s" % need
print("ROUND 2 PATCHES APPLIED")
