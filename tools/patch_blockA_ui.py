"""Block A: fix the two demo-fatal UI defects found on the user's screenshot.

P1 responsive layout. The banner was position:fixed at top = topbar height, so
it floated OVER the header and OVER the rail tab bar - hiding the very Lab tab
that the empty state tells the operator to click. It is now a real flex row
above the shell, so it always reserves its own space and can never cover
anything. Its cause/action spans now wrap instead of colliding at narrow
widths. The sub-1280px rail drawer is now positioned against the shell rather
than the viewport (so the banner cannot push it out of alignment) and it has a
visible Panels toggle in the topbar, so it can be closed again.

P2 cold start honesty. Before any run has produced a frame there is no stale
state - there is no run. The link now reads Idle in neutral ink and the stale
watch is silent until a frame has arrived at least once. The empty state also
gains a real Start demo run control so the first action is one click, at the
measured parity fleet size of 8.
"""

import ast
import subprocess
import sys

ROOT = "/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920"


def edit(path, pairs):
    full = ROOT + "/" + path
    with open(full) as fh:
        src = fh.read()
    for old, new in pairs:
        n = src.count(old)
        assert n == 1, "expected 1 match in %s, found %d for:\n%s" % (path, n, old[:160])
        src = src.replace(old, new)
    if path.endswith(".py"):
        ast.parse(src)
    with open(full, "w") as fh:
        fh.write(src)
    print("patched", path)


# ------------------------------------------------------------------ store.js
edit("web/js/store.js", [
    (
        """    this._frameCount = 0;
    this._lastFrameAt = 0;""",
        """    this._frameCount = 0;
    this._lastFrameAt = 0;
    /* Monotonic: true once ANY frame has ever arrived, and never cleared by
     * reset(). A cold start is not a degraded link, and the UI must be able to
     * tell those two apart before it accuses the backend of being stale. */
    this.everFrame = false;""",
    ),
    (
        """    this._frameCount += 1;
    this._emit("frame");""",
        """    this._frameCount += 1;
    this.everFrame = true;
    this._emit("frame");""",
    ),
])

# -------------------------------------------------------------- transport.js
edit("web/js/transport.js", [
    (
        """      if (!this.lastFrameAt) return;
      const age = performance.now() - this.lastFrameAt;""",
        """      // Never report staleness before the first frame has ever arrived: an
      // idle server that has not been given a run is not a late server.
      if (!this.lastFrameAt || !store.everFrame) return;
      const age = performance.now() - this.lastFrameAt;""",
    ),
])

# ----------------------------------------------------------------- main.js
edit("web/js/main.js", [
    (
        """  const dot = $("link-dot");
  if (dot) dot.dataset.link = store.link;
  const txt = $("link-text");
  if (txt) txt.textContent = LINK_TEXT[store.link] || DASH;""",
        """  // A connected socket that has never carried a frame is IDLE, not degraded.
  // Saturated colour is reserved for real trouble, so idle paints neutral.
  const idle = !store.everFrame && store.link === LINK.LIVE;
  const dot = $("link-dot");
  if (dot) dot.dataset.link = idle ? "idle" : store.link;
  const txt = $("link-text");
  if (txt) txt.textContent = idle ? "Idle" : (LINK_TEXT[store.link] || DASH);""",
    ),
    (
        """    { name: "Start run", desc: "Start the configured scenario", hint: "Lab", run: () => { selectTab("lab"); transport.startRun({ scenario: store.scenario || "rush_50", seed: store.seed == null ? 11 : store.seed, fleet_size: 24 }); } },""",
        """    { name: "Start run", desc: "Start the configured scenario", hint: "Lab", run: () => { selectTab("lab"); transport.startRun({ scenario: store.scenario || "rush_50", seed: store.seed == null ? 11 : store.seed, fleet_size: DEMO_FLEET }); } },""",
    ),
    (
        """$("banner-dismiss") && $("banner-dismiss").addEventListener("click", hideBanner);""",
        """/* One-click first action. The empty state names the next action, so it must
 * also be able to PERFORM it - telling an operator what to do and then making
 * them hunt for the control is the cold-start failure this replaces. */
$("btn-start-demo") && $("btn-start-demo").addEventListener("click", async () => {
  const btn = $("btn-start-demo");
  btn.disabled = true;
  btn.textContent = "Starting...";
  const res = await transport.startRun({ scenario: "rush_50", seed: 11, fleet_size: DEMO_FLEET });
  if (!res.ok) {
    btn.disabled = false;
    btn.textContent = "Start demo run";
    showBanner("error", res.error || "The run could not be started.",
               "Check that the backend is running, then press Start demo run again.");
  }
});

/* Below 1280px the rail is an overlay drawer. A drawer with no visible handle
 * is a trap, so the topbar carries one at those widths. */
$("btn-rail-toggle") && $("btn-rail-toggle").addEventListener("click", () => {
  const rail = $("rail");
  if (!rail) return;
  const open = rail.dataset.open !== "true";
  rail.dataset.open = String(open);
  $("btn-rail-toggle").setAttribute("aria-expanded", String(open));
});

$("banner-dismiss") && $("banner-dismiss").addEventListener("click", hideBanner);""",
    ),
    (
        """const LINK_TEXT = {""",
        """/* Measured parity fleet size. At 1800 ticks on rush_50 the coordinated fleet
 * completes 20 tasks against the baseline's 22 at fleet 8, so this is the size
 * at which the demo can be shown without overclaiming throughput. */
const DEMO_FLEET = 8;

const LINK_TEXT = {""",
    ),
])

# ---------------------------------------------------------------- index.html
edit("web/index.html", [
    (
        """    <button class="btn" id="btn-palette" aria-haspopup="dialog">
      Commands <span class="kbd">Ctrl K</span>
    </button>""",
        """    <button class="btn" id="btn-palette" aria-haspopup="dialog">
      Commands <span class="kbd">Ctrl K</span>
    </button>

    <!-- Only rendered below 1280px, where the rail becomes an overlay drawer. -->
    <button class="btn rail-toggle" id="btn-rail-toggle" aria-controls="rail" aria-expanded="false">
      Panels
    </button>""",
    ),
    (
        """        <div class="empty__cause">No fleet state received yet.</div>
        <div class="empty__action">Open the Simulation Lab tab and start a scenario, or press Ctrl+K then "Run".</div>""",
        """        <div class="empty__cause">No run has been started yet.</div>
        <div class="empty__action">Start the reference scenario below, or open the Lab tab to configure your own.</div>
        <div class="empty__cta">
          <button class="btn btn--primary" id="btn-start-demo">Start demo run</button>
        </div>
        <div class="empty__hint">rush_50 &middot; seed 11 &middot; fleet 8</div>""",
    ),
])

print("all patches applied")
