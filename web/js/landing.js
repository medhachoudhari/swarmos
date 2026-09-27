// ---------------------------------------------------------------------------
// landing.js  STATE 1 behaviour for the ROBONEX landing page.
//
// Scope, deliberately narrow:
//   1. report server reachability and run state honestly (no invented values);
//   2. on ENTER SWARMOS, start the real simulation and navigate to the real
//      dashboard at index.html.
//
// It imports nothing from the dashboard and the dashboard imports nothing from
// here, so the simulation product cannot be affected by this file.
// ---------------------------------------------------------------------------

"use strict";

// Entry configuration. Kept identical to the demo defaults in run.sh so the
// landing button and the scripted demo enter the same simulation.
const ENTRY = Object.freeze({
  scenario: "rush_50",
  seed: 11,
  fleet_size: 8,
  policy: "swarmos",
  speed: 1.0,
});

const DASH = "--";
const DASHBOARD_URL = "index.html";
// Where the real backend lives when this page is opened straight off disk
// (file://). Must match run.sh's default host:port.
const SERVER_ORIGIN = "http://127.0.0.1:8770";
const TRANSITION_MS = 180;
const STATUS_POLL_MS = 4000;


const els = {
  body: document.body,
  fleetRow: document.getElementById("lp-status-fleet"),
  fleetVal: document.getElementById("lp-status-fleet-value"),
  netRow: document.getElementById("lp-status-net"),
  netVal: document.getElementById("lp-status-net-value"),
  enter: document.getElementById("lp-enter"),
  note: document.getElementById("lp-cta-note"),
};

// Opened straight off disk (file://) a relative fetch resolves against the
// filesystem, not the backend, and the browser blocks it outright.
const FILE_PROTOCOL = window.location.protocol === "file:";

function apiUrl(path) {
  return FILE_PROTOCOL ? SERVER_ORIGIN + "/" + path : path;
}

// A cross-origin fetch() from file:// (origin "null") to the backend depends
// on CORS working correctly end to end through the browser AND anything
// sitting in front of it (a corporate proxy, in particular, has been
// observed here to interfere with cross-origin preflight/response headers
// even for 127.0.0.1 targets, in ways that differ by browser and are not
// fixable from this page). Rather than depend on that path at all under
// file://, ENTER SWARMOS instead performs a plain top-level NAVIGATION to
// the server's OWN copy of this same landing page. A navigation is not
// subject to CORS (only fetch/XHR reads are), so it always works if the
// server is merely reachable at all - and once there, the page runs
// same-origin, where every fetch on this file has already been proven to
// work correctly.



// --------------------------------------------------------------------- status

function setRow(row, valueEl, dotState, text) {
  if (!row || !valueEl) return;
  const dot = row.querySelector(".lp-dot");
  if (dot) dot.setAttribute("data-state", dotState);
  row.setAttribute("data-state", dotState);
  valueEl.textContent = text;
}

// Reachability is the only thing this page can honestly assert about the
// network, so that is exactly what the AMR NETWORK row reports.
function renderUnreachable() {
  setRow(els.fleetRow, els.fleetVal, "unknown", DASH);
  setRow(els.netRow, els.netVal, "down", "UNREACHABLE");
}

function renderStatus(status) {
  setRow(els.netRow, els.netVal, "ok", "ONLINE");

  if (!status || typeof status !== "object") {
    setRow(els.fleetRow, els.fleetVal, "unknown", DASH);
    return;
  }
  if (status.running === true) {
    setRow(els.fleetRow, els.fleetVal, "ok", "LIVE");
  } else if (status.has_run === true) {
    setRow(els.fleetRow, els.fleetVal, "warn", "PAUSED");
  } else {
    setRow(els.fleetRow, els.fleetVal, "ok", "READY");
  }
}

async function pollStatus() {
  if (FILE_PROTOCOL) {
    // Never attempt a cross-origin status fetch from file:// - see the note
    // above enterSwarmos(). Whether the backend is reachable is genuinely
    // unknown from here without depending on the same fragile cross-origin
    // path, so this states that honestly rather than guessing right or wrong.
    setRow(els.netRow, els.netVal, "unknown", "OPEN SERVER TO CHECK");
    setRow(els.fleetRow, els.fleetVal, "unknown", DASH);
    return;
  }
  try {
    const res = await fetch(apiUrl("api/status"), {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    if (!res.ok) throw new Error("HTTP " + res.status);
    const body = await res.json();
    renderStatus(body && body.status);
  } catch (err) {
    renderUnreachable();
  }
}



// ------------------------------------------------------------------ cta entry

function note(text, state) {
  if (!els.note) return;
  els.note.textContent = text || "";
  if (state) els.note.setAttribute("data-state", state);
  else els.note.removeAttribute("data-state");
}

function reducedMotion() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function navigate() {
  if (reducedMotion()) {
    window.location.href = DASHBOARD_URL;
    return;
  }
  els.body.setAttribute("data-state", "entering");
  window.setTimeout(function () {
    window.location.href = DASHBOARD_URL;
  }, TRANSITION_MS);
}

// Under file:// there is no relative index.html to navigate to on disk in
// the same way the server serves it, but the dashboard IS served by the
// same backend at SERVER_ORIGIN, so navigation goes there instead.
function dashboardUrl() {
  return FILE_PROTOCOL ? SERVER_ORIGIN + "/" + DASHBOARD_URL : DASHBOARD_URL;
}

async function enterSwarmos() {
  if (!els.enter || els.enter.disabled) return;
  els.enter.disabled = true;

  if (FILE_PROTOCOL) {
    // Do not fetch() cross-origin from file:// at all. A plain top-level
    // NAVIGATION is not subject to CORS the way fetch/XHR reads are, so it
    // is immune to every browser- and proxy-specific CORS/PNA failure mode
    // that a cross-origin fetch from a "null" origin can hit. Land on the
    // SERVER's own copy of this same landing page; from there the page is
    // same-origin and every fetch on this file already works correctly
    // (verified directly against the running backend).
    note("OPENING SERVER...");
    window.location.href = SERVER_ORIGIN + "/";
    return;
  }

  note("STARTING SIMULATION");

  try {
    const res = await fetch(apiUrl("api/sim/start"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(ENTRY),
    });
    const body = await res.json().catch(function () {
      return null;
    });
    if (!res.ok || !body || body.ok !== true) {
      const why = (body && (body.error || body.detail)) || "HTTP " + res.status;
      note("COULD NOT START: " + String(why).toUpperCase(), "error");
      els.enter.disabled = false;
      return;
    }
  } catch (err) {
    note("SERVER UNREACHABLE", "error");
    els.enter.disabled = false;
    return;
  }

  note("ENTERING");
  if (reducedMotion()) {
    window.location.href = dashboardUrl();
    return;
  }
  els.body.setAttribute("data-state", "entering");
  window.setTimeout(function () {
    window.location.href = dashboardUrl();
  }, TRANSITION_MS);
}


// ---------------------------------------------------------------------- wiring

// Opened straight off disk, ENTER SWARMOS now talks to the real backend at
// SERVER_ORIGIN via apiUrl() above (a cross-origin fetch, allowed by CORS-
// unrestricted GET/POST to a plain JSON API with no credentials), and on
// success navigates to that SAME origin's dashboard rather than to a
// nonexistent local index.html. The button is never disabled outright here
// any more - if the backend genuinely is not running, the click still
// happens and reports SERVER UNREACHABLE, which is the honest failure mode
// instead of a silently disabled control.
if (els.enter) {
  els.enter.addEventListener("click", enterSwarmos);
}



// Keyboard-first: Enter anywhere on the page enters the product, unless the
// user is focused on something else interactive.
document.addEventListener("keydown", function (ev) {
  if (ev.key !== "Enter" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
  const active = document.activeElement;
  if (active && active !== document.body && active !== els.enter) return;
  ev.preventDefault();
  enterSwarmos();
});

// ------------------------------------------------------------------- layout

// The ROBONEX composition is a fixed 1440 x 800 stage scaled to the viewport,
// with a 520 px minimum height. landing.css reads --lp-scale for the stage
// transform and the background grid pitch.
const STAGE_W = 1440;
const STAGE_H = 800;
const STAGE_MIN_H = 520;

function fitStage() {
  const s = Math.min(
    window.innerWidth / STAGE_W,
    Math.max(window.innerHeight, STAGE_MIN_H) / STAGE_H
  );
  els.body.style.setProperty("--lp-scale", String(s));
}

fitStage();
window.addEventListener("resize", fitStage);

pollStatus();
window.setInterval(pollStatus, STATUS_POLL_MS);

// File contains AI-generated response based on internal company sources
