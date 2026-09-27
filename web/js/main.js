/* Bootstrap.
 *
 * This file owns exactly one thing: wiring. It creates the transport, the map
 * renderer, the four rail panels and the palette, then subscribes ONCE to the
 * store and fans that single notification out to whatever is currently visible.
 * Hidden panels are not re-rendered -- at 10 Hz with 50 robots that difference
 * is the whole frame budget.
 *
 * No data is invented here. Every readout that has no value renders "--".
 */
import { store, LINK, STATES } from "./store.js";
import { Transport } from "./transport.js";
import { MapView } from "./map.js";
import { FleetPanel } from "./panels/fleet.js";
import { InspectorPanel } from "./panels/inspector.js";
import { LabPanel } from "./panels/lab.js";
import { AnalyticsPanel } from "./panels/analytics.js";
import { CosimPanel } from "./panels/cosim.js";
import { CosimClient } from "./cosim.js";
import { Palette } from "./palette.js";
import { num, int, secs, DASH } from "./format.js";

const $ = (id) => document.getElementById(id);

/* Measured parity fleet size. At 1800 ticks on rush_50 the coordinated fleet
 * completes 20 tasks against the baseline's 22 at fleet 8, so this is the size
 * at which the demo can be shown without overclaiming throughput. */
const DEMO_FLEET = 8;

const LINK_TEXT = {
  [LINK.LIVE]: "Live",
  [LINK.DEGRADED]: "Degraded",
  [LINK.DOWN]: "Disconnected",
};

/* ---------------------------------------------------------------- banner --- */

let bannerState = null; // {tone, cause, action, onAction}

function showBanner(tone, cause, action, onAction) {
  bannerState = { tone, cause, action, onAction };
  paintBanner();
}

function hideBanner() {
  bannerState = null;
  paintBanner();
}

function paintBanner() {
  const el = $("banner");
  if (!el) return;
  if (!bannerState) {
    el.dataset.visible = "false";
    return;
  }
  el.dataset.visible = "true";
  el.dataset.tone = bannerState.tone;
  $("banner-cause").textContent = bannerState.cause;
  const act = $("banner-action");
  act.textContent = bannerState.action || "";
  act.hidden = !bannerState.action;
}

/* ------------------------------------------------------------------ boot --- */

const transport = new Transport({
  onBanner: (b) => {
    if (!b) { hideBanner(); return; }
    showBanner(b.tone || "warn", b.cause || "Connection problem.", b.action || "Retry now", () => transport.retryNow());
  },
});

const map = new MapView($("map"));

/* The co-simulation is a second, independent stream. It is constructed
 * unconditionally but connects only when a comparison is started, so an
 * operator who never opens the Compare tab pays nothing for it. */
const cosim = new CosimClient(transport);

/* The map asks for ghosts every animation frame; the client decides
 * whether there are any it can honestly supply. The scenario and seed of
 * the LIVE run are the gate: a comparison of a different warehouse must
 * never be painted over this one. */
map.ghostSource = () => cosim.ghostSource(store.scenario, store.seed);

const panels = {
  fleet: new FleetPanel($("panel-fleet"), map),
  inspector: new InspectorPanel($("panel-inspector")),
  lab: new LabPanel($("panel-lab"), transport),
  cosim: new CosimPanel($("panel-cosim"), cosim),
  analytics: new AnalyticsPanel($("panel-analytics")),
};

let activeTab = "fleet";

/* ------------------------------------------------------------------ tabs --- */

/* reveal=true means "the user asked for this panel", so show the rail.
 * reveal=false is the boot path: choose the default panel but leave the rail
 * closed, which is what section 15 requires of state 2. */
function selectTab(name, reveal = true) {
  activeTab = name;
  for (const key of Object.keys(panels)) {
    const tab = $(`tab-${key}`);
    const panel = $(`panel-${key}`);
    const on = key === name;
    if (tab) tab.setAttribute("aria-selected", String(on));
    if (panel) panel.dataset.active = String(on);
  }
  panels[name].render();
  if (reveal) setRailOpen(true);
}

for (const key of Object.keys(panels)) {
  const tab = $(`tab-${key}`);
  if (!tab) continue;
  tab.addEventListener("click", () => selectTab(key));
  tab.addEventListener("keydown", (e) => {
    const order = Object.keys(panels);
    const i = order.indexOf(key);
    if (e.key === "ArrowRight") { e.preventDefault(); selectTab(order[(i + 1) % order.length]); $(`tab-${order[(i + 1) % order.length]}`).focus(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); const p = order[(i - 1 + order.length) % order.length]; selectTab(p); $(`tab-${p}`).focus(); }
  });
}

/* ---------------------------------------------------------------- legend --- */

const hidden = new Set();

function buildLegend() {
  const el = $("legend");
  if (!el) return;
  el.innerHTML = STATES.map((s) => `
    <button class="legend__row" data-state="${s}" data-muted="${hidden.has(s)}" type="button"
            aria-pressed="${!hidden.has(s)}" title="Show or hide ${s} robots">
      <span class="legend__swatch" data-outline="${s === "AVAILABLE"}" style="background:var(--state-${s.toLowerCase()});border-color:var(--state-${s.toLowerCase()})"></span>
      <span>${s}</span>
      <span class="legend__count num" data-count="${s}">${DASH}</span>
    </button>`).join("");
  el.querySelectorAll(".legend__row").forEach((row) => {
    row.addEventListener("click", () => {
      const s = row.dataset.state;
      if (hidden.has(s)) hidden.delete(s); else hidden.add(s);
      row.dataset.muted = String(hidden.has(s));
      row.setAttribute("aria-pressed", String(!hidden.has(s)));
      if (typeof map.toggleState === "function") map.toggleState(s);
    });
  });
}

function paintLegendCounts() {
  const counts = store.countByState();
  for (const s of STATES) {
    const n = document.querySelector(`[data-count="${s}"]`);
    if (n) n.textContent = store.hasData ? int(counts[s] || 0) : DASH;
  }
}

/* ------------------------------------------------------------ topbar/kpi --- */

function paintTopbar() {
  // A connected socket that has never carried a frame is IDLE, not degraded.
  // Saturated colour is reserved for real trouble, so idle paints neutral.
  const idle = !store.everFrame && store.link === LINK.LIVE;
  const dot = $("link-dot");
  if (dot) dot.dataset.link = idle ? "idle" : store.link;
  const txt = $("link-text");
  if (txt) txt.textContent = idle ? "Idle" : (LINK_TEXT[store.link] || DASH);
  const sc = $("hdr-scenario");
  if (sc) sc.textContent = store.scenario || DASH;
  const sd = $("hdr-seed");
  if (sd) sd.textContent = store.seed == null ? DASH : int(store.seed);
  const tk = $("hdr-tick");
  if (tk) tk.textContent = store.hasData ? int(store.tick) : DASH;
  const ck = $("hdr-clock");
  if (ck) ck.textContent = store.hasData ? `${secs(store.simTime)} s` : DASH;
}

/* kpis().verdicts is a nested map of kind -> count, not a scalar. Passing it
 * straight to int() produced NaN on screen for the whole run. Sum the counts,
 * and keep DASH for "no data" so a missing value is never drawn as a zero. */
function verdictTotal(verdicts) {
  if (verdicts == null) return DASH;
  if (typeof verdicts === "number") return int(verdicts);
  const counts = Object.values(verdicts).filter((v) => typeof v === "number");
  if (!counts.length) return DASH;
  return int(counts.reduce((a, b) => a + b, 0));
}

function paintKpis() {
  const k = store.kpis || {};
  const set = (id, v) => { const n = $(id); if (n) n.textContent = v; };
  set("kpi-tasks-per-min", k.tasks_per_min == null ? DASH : num(k.tasks_per_min, 2));
  set("kpi-tasks-complete", k.tasks_complete == null ? DASH : int(k.tasks_complete));
  set("kpi-collisions", k.collisions == null ? DASH : int(k.collisions));
  set("kpi-p95", k.compute && k.compute.p95_ms != null ? num(k.compute.p95_ms, 1) : DASH);
  set("kpi-avg-completion", k.avg_completion_s == null ? DASH : num(k.avg_completion_s, 1));
  set("kpi-verdicts", verdictTotal(k.verdicts));
  set("kpi-replans", k.replans == null ? DASH : int(k.replans));
}

/* ------------------------------------------------------------- map chrome --- */

function paintMapInfo() {
  const z = $("info-zoom");
  if (z) {
    const zoom = typeof map.zoom === "number" ? map.zoom : (typeof map.scale === "function" ? map.scale() : null);
    z.textContent = zoom == null ? DASH : `${num(zoom, 2)}x`;
  }
  const f = $("info-fps");
  if (f) f.textContent = map.fps == null ? DASH : int(map.fps);
}

$("btn-zoom-in") && $("btn-zoom-in").addEventListener("click", () => { map.zoomBy(1.2); paintMapInfo(); });
$("btn-zoom-out") && $("btn-zoom-out").addEventListener("click", () => { map.zoomBy(1 / 1.2); paintMapInfo(); });
$("btn-zoom-fit") && $("btn-zoom-fit").addEventListener("click", () => { map.fit(); paintMapInfo(); });

const hit = $("layer-hit");
if (hit) {
  hit.addEventListener("mousemove", (e) => {
    const cur = $("info-cursor");
    if (!cur || typeof map.toWorld !== "function") return;
    const r = hit.getBoundingClientRect();
    // map.toWorld() returns a plain [x, y] array, not an {x, y} object.
    // This used to read w.x / w.y, which are undefined on an array, so the
    // readout always rendered "--, -- m" no matter where the mouse was.
    const w = map.toWorld(e.clientX - r.left, e.clientY - r.top);
    cur.textContent = w ? `${num(w[0], 1)}, ${num(w[1], 1)} m` : DASH;
  });

  hit.addEventListener("mouseleave", () => {
    const cur = $("info-cursor");
    if (cur) cur.textContent = DASH;
  });
}

/* ---------------------------------------------------------------- palette --- */

const palette = new Palette({
  scrim: $("palette-scrim"),
  input: $("palette-input"),
  list: $("palette-list"),
  commands: [
    { name: "Start run", desc: "Start the configured scenario", run: () => { selectTab("lab"); transport.startRun({ scenario: store.scenario || "rush_50", seed: store.seed == null ? 11 : store.seed, fleet_size: DEMO_FLEET }); } },
    { name: "Pause / resume", desc: "Toggle the 10 Hz tick loop", run: () => (store.running ? transport.pauseRun() : transport.resumeRun()) },
    { name: "Step one tick", desc: "Advance exactly 100 ms of sim time", run: () => transport.stepRun(1) },
    { name: "Stop run", desc: "Halt the run and release the fleet", run: () => transport.stopRun() },
    { name: "Fit map to warehouse", desc: "Reset zoom and pan", hint: "0", run: () => { map.fit(); paintMapInfo(); } },
    { name: "Clear selection", desc: "Deselect the inspected robot", hint: "Esc", run: () => store.select(null) },
    { name: "Open decision inspector", desc: "Show the advisory / binding / applied chain", run: () => selectTab("inspector") },
    { name: "Open analytics", desc: "Throughput, blocking, compute budget, message load", run: () => selectTab("analytics") },
  ],
});

$("btn-palette") && $("btn-palette").addEventListener("click", () => {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }));
});

/* One-click first action. The empty state names the next action, so it must
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

/* One toggle, two mechanisms. Above 1280px the rail is a grid column and the
 * shell gives its width back to the map; below, it is an overlay drawer. Both
 * are driven from the same handle so the keyboard path is identical. */
function isRailOpen() {
  const shell = $("shell");
  const rail = $("rail");
  if (shell && window.innerWidth > 1280) return shell.dataset.rail === "open";
  return !!rail && rail.dataset.open === "true";
}

function setRailOpen(open) {
  const shell = $("shell");
  const rail = $("rail");
  if (shell) shell.dataset.rail = open ? "open" : "closed";
  if (rail) rail.dataset.open = String(open);
  const handle = $("btn-rail-toggle");
  if (handle) handle.setAttribute("aria-expanded", String(open));
}

$("btn-rail-toggle") && $("btn-rail-toggle").addEventListener("click", () => {
  setRailOpen(!isRailOpen());
});

$("banner-dismiss") && $("banner-dismiss").addEventListener("click", hideBanner);
$("banner-action") && $("banner-action").addEventListener("click", () => {
  if (bannerState && typeof bannerState.onAction === "function") bannerState.onAction();
});

/* -------------------------------------------------------------- the pump --- */

let lastTick = -1;

store.subscribe(() => {
  paintTopbar();
  paintKpis();
  paintLegendCounts();

  const ph = $("map-placeholder");
  if (ph) ph.dataset.hidden = String(store.hasData);

  if (store.tick !== lastTick) {
    lastTick = store.tick;
    map.onFrame();
  }

  // Only the visible panel re-renders. Lab is cheap and holds live run state,
  // so it is also refreshed when visible.
  panels[activeTab].render();
  paintMapInfo();
});

cosim.subscribe(() => {
  if (activeTab === "cosim") panels.cosim.render();
});

window.addEventListener("resize", () => {
  map.resize();
  paintMapInfo();
});

/* Global shortcuts. Every key advertised in the command palette or in a
 * banner action string must be bound here, otherwise the UI promises
 * something it does not do. A key is swallowed while the user is typing
 * in a field, while a modifier is held, or while the palette is open. */
function typingTarget(t) {
  if (!t || !t.tagName) return false;
  const tag = t.tagName.toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return true;
  return t.isContentEditable === true;
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (store.selectedRobot) store.select(null);
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (typingTarget(e.target)) return;
  if (palette && palette.open) return;

  if (e.key === "0") {
    e.preventDefault();
    map.fit();
    paintMapInfo();
  } else if (e.key === "r" || e.key === "R") {
    e.preventDefault();
    transport.retryNow();
  }
});

selectTab("fleet", false);   /* panels closed on entry (section 15) */
buildLegend();
paintTopbar();
paintKpis();
paintLegendCounts();
map.resize();
map.fit();
map.start();
paintMapInfo();
panels.lab.init();
panels.cosim.init();
transport.connect();

// File contains AI-generated response based on internal company sources
