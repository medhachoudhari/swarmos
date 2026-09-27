/* Simulation Lab.
 *
 * Run control plus the determinism receipt (novelty N3). The receipt is the
 * only honest way to SHOW determinism in a live demo: run a seed, record the
 * trace hash, re-run the same seed, and compare the two hashes on screen. If
 * they differ the panel says so in plain words rather than hiding it.
 *
 * Every control here is disabled when the transport is not live, because a
 * button that silently does nothing is worse than a button that is visibly
 * unavailable.
 */
import { store, LINK } from "../store.js";
import { shortHash, int } from "../format.js";

const FAULTS = [
  { id: "robot_failure", label: "Robot failure (kill one robot)" },
  { id: "comm_blackout", label: "Comm blackout (cut one robot's radio 6 s)" },
  { id: "link_impair", label: "Link impairment (drops and latency, fleet-wide)" },
  { id: "blocked_aisle", label: "Block an aisle (static obstacle)" },
  { id: "rogue_agent", label: "Rogue agent (adversarial robot)" },
];

const CFG_KEYS = ["scenario", "seed", "fleet_size", "policy", "integrity"];

// A capture is { hash, tick, config, run }, where `run` counts the Starts
// issued from this panel. A capture from the baseline's own run (or with no
// baseline yet) becomes the baseline; a capture from any later run is the
// re-run side. A run can therefore never be compared against itself.
export function placeCapture(baseline, rec) {
  if (!baseline || rec.run === baseline.run) return { baseline: rec, rerun: null };
  return { baseline, rerun: rec };
}

// Compare needs two captures from two distinct runs at the same tick.
export function canCompare(baseline, rerun) {
  return Boolean(baseline && rerun && baseline.hash && rerun.hash
    && rerun.run !== baseline.run && rerun.tick === baseline.tick);
}

// "identical", "mismatch", or null when the two captures are not comparable.
export function compareCaptures(baseline, rerun) {
  if (!canCompare(baseline, rerun)) return null;
  return baseline.hash === rerun.hash ? "identical" : "mismatch";
}

export function sameConfig(a, b) {
  if (!a || !b) return false;
  return CFG_KEYS.every((k) => a[k] === b[k]);
}

function describe(rec) {
  if (!rec) return "";
  const c = rec.config;
  const at = rec.tick === null ? "tick --" : `tick ${int(rec.tick)}`;
  return c ? `${at} \u00b7 ${c.scenario} \u00b7 seed ${c.seed} \u00b7 fleet ${c.fleet_size}` : at;
}

export class LabPanel {
  constructor(el, transport) {
    this.el = el;
    this.transport = transport;
    this.scenarios = null;
    this.baseline = null;
    this.rerun = null;
    this.result = null;
    this.runSeq = 0;
    this.busy = false;
    this._built = false;
    this._note = "";
  }

  async init() {
    const res = await this.transport.scenarios();
    if (res.ok && Array.isArray(res.data && res.data.scenarios)) {
      this.scenarios = res.data.scenarios;
    } else {
      this.scenarios = null;
      this._note = res.error ? `Scenario list unavailable: ${res.error}` : "";
    }
    this.render();
  }

  render() {
    if (!this._built) this._build();
    this._update();
  }

  _build() {
    const opts = this.scenarios
      // The server key is ScenarioSpec.as_dict().name. There is no 'id'
      // field, so a fallback must land on another FIELD, never on the
      // whole record - that is what produced value="[object Object]".
      ? this.scenarios.map((s) => `<option value="${s.name}">${s.title || s.name}</option>`).join("")
      : `<option value="rush_50">rush_50</option>
         <option value="narrow_aisle_deadlock">narrow_aisle_deadlock</option>
         <option value="blocked_aisle">blocked_aisle</option>`;

    this.el.innerHTML = `
      <h2 class="panel__title">Run configuration</h2>
      <div class="field">
        <label class="field__label" for="lab-scenario">Scenario</label>
        <select class="field__control" id="lab-scenario">${opts}</select>
        <div class="field__hint" id="lab-scenario-hint">${this.scenarios ? "Loaded from the server." : "Server list unavailable; showing the built-in scenarios."}</div>
      </div>
      <div class="field">
        <label class="field__label" for="lab-fleet">Fleet size</label>
        <input class="field__control num" id="lab-fleet" type="number" min="1" max="50" step="1" value="24">
        <div class="field__hint">Sustained 10 Hz is verified up to 50 robots.</div>
      </div>
      <div class="field">
        <label class="field__label" for="lab-seed">Seed</label>
        <input class="field__control num" id="lab-seed" type="number" min="0" step="1" value="11">
        <div class="field__hint">Same seed and same scenario must reproduce the same trace hash.</div>
      </div>
      <div class="field">
        <label class="field__label" for="lab-integrity">Message integrity</label>
        <select class="field__control" id="lab-integrity">
          <option value="off" selected>Off</option>
          <option value="on">Signed messages and sentinel council</option>
        </select>
        <div class="field__hint">When on, robots sign their broadcasts and neighbours
          cross-check position claims. Two independent witnesses are required before
          any robot is contained. Off by default, and off changes nothing: the trace
          hash is identical either way.</div>
      </div>
      <div class="btn-row">
        <button class="btn btn--primary" id="lab-start">Start</button>
        <button class="btn" id="lab-pause">Pause</button>
        <button class="btn" id="lab-step">Step</button>
        <button class="btn" id="lab-stop">Stop</button>
      </div>
      <div class="field__hint" id="lab-note"></div>

      <div class="panel__section">
        <h2 class="panel__title">Fault injection</h2>
        <div class="field">
          <label class="field__label" for="lab-fault">Fault</label>
          <select class="field__control" id="lab-fault">
            ${FAULTS.map((f) => `<option value="${f.id}">${f.label}</option>`).join("")}
          </select>
          <div class="field__hint">Faults are injected into the live run at the next tick boundary.</div>
        </div>
        <div class="btn-row"><button class="btn" id="lab-inject">Inject</button></div>
      </div>

      <div class="panel__section">
        <h2 class="panel__title">Determinism receipt</h2>
        <div class="field__hint">Capture the hash of Run 1, start a fresh run with the same seed, capture it at the same tick, then compare.</div>
        <div class="btn-row">
          <button class="btn" id="lab-capture">Capture hash</button>
          <button class="btn" id="lab-compare">Compare now</button>
          <button class="btn" id="lab-hash-clear">Clear</button>
        </div>
        <div id="lab-hashes"></div>
      </div>`;

    const on = (id, fn) => this.el.querySelector(id).addEventListener("click", fn);
    on("#lab-start", () => this._start());
    on("#lab-pause", () => this._pause());
    on("#lab-step", () => this._guard(() => this.transport.stepRun(1)));
    on("#lab-stop", () => this._guard(() => this.transport.stopRun()));
    on("#lab-inject", () => this._inject());
    on("#lab-capture", () => this._capture());
    on("#lab-compare", () => this._compare());
    on("#lab-hash-clear", () => this._clearHashes());
    this._built = true;
  }

  _cfg() {
    return {
      scenario: this.el.querySelector("#lab-scenario").value,
      fleet_size: Number(this.el.querySelector("#lab-fleet").value),
      seed: Number(this.el.querySelector("#lab-seed").value),
      integrity: this.el.querySelector("#lab-integrity").value === "on",
    };
  }

  async _guard(fn) {
    if (this.busy) return;
    this.busy = true;
    this._update();
    const res = await fn();
    this.busy = false;
    this._note = res && res.ok === false ? res.error || "Request failed." : "";
    this.render();
  }

  _start() {
    // The baseline capture survives Start: it is the Run 1 side of the replay
    // comparison. Only the re-run side and the last verdict are reset.
    return this._guard(async () => {
      const res = await this.transport.startRun(this._cfg());
      if (res && res.ok !== false) {
        this.runSeq += 1;
        this.rerun = null;
        this.result = null;
      }
      return res;
    });
  }

  _pause() {
    return this._guard(() => (store.running ? this.transport.pauseRun() : this.transport.resumeRun()));
  }

  _inject() {
    const fault = this.el.querySelector("#lab-fault").value;
    const target = store.selectedRobot || null;
    return this._guard(() => this.transport.injectFault({ fault, robot_id: target }));
  }

  async _capture() {
    const res = await this.transport.traceHash();
    const d = (res.ok && res.data) || {};
    const h = d.hash || d.trace_hash;
    if (!h) {
      this._note = res.error || "Trace hash unavailable.";
      this.render();
      return;
    }
    // `tick` is the API's completed-tick count, the point the hash covers.
    const rec = { hash: h, tick: Number.isFinite(d.tick) ? d.tick : null, config: d.config || null, run: this.runSeq };
    ({ baseline: this.baseline, rerun: this.rerun } = placeCapture(this.baseline, rec));
    this.result = null;
    this._note = "";
    this.render();
  }

  _compare() {
    this.result = compareCaptures(this.baseline, this.rerun);
    this.render();
  }

  _clearHashes() {
    this.baseline = null;
    this.rerun = null;
    this.result = null;
    this.render();
  }

  _update() {
    const live = store.link !== LINK.DOWN;
    const dis = (id, cond) => { const n = this.el.querySelector(id); if (n) n.disabled = cond; };
    dis("#lab-start", !live || this.busy);
    dis("#lab-pause", !live || this.busy || !store.hasData);
    dis("#lab-step", !live || this.busy || !store.hasData);
    dis("#lab-stop", !live || this.busy || !store.hasData);
    dis("#lab-inject", !live || this.busy || !store.hasData);
    dis("#lab-capture", !live || this.busy || !store.hasData);
    dis("#lab-compare", this.busy || !canCompare(this.baseline, this.rerun));
    dis("#lab-hash-clear", this.busy || !this.baseline);

    const pause = this.el.querySelector("#lab-pause");
    if (pause) pause.textContent = store.hasData && !store.running ? "Resume" : "Pause";

    const note = this.el.querySelector("#lab-note");
    if (note) {
      note.textContent = this._note
        ? this._note
        : live
          ? `Tick ${int(store.tick)} \u00b7 ${store.running ? "running" : store.hasData ? "paused" : "idle"}`
          : "Backend is not connected. Run controls are unavailable.";
    }

    const box = this.el.querySelector("#lab-hashes");
    if (!box) return;
    if (!this.baseline) {
      box.innerHTML = `<div class="empty">
        <div class="empty__cause">No hash captured yet.</div>
        <div class="empty__action">Run a scenario, then press Capture hash.</div>
      </div>`;
      return;
    }
    const b = this.baseline;
    const r = this.rerun;
    const match = this.result === null ? "" : String(this.result === "identical");
    let hint;
    if (!r) {
      hint = `Start a fresh run with the same configuration, advance it to tick ${int(b.tick)}, then press Capture hash.`;
    } else if (r.tick !== b.tick) {
      hint = r.tick < b.tick
        ? `Run 2 was captured at tick ${int(r.tick)}. Advance it to tick ${int(b.tick)} and capture again.`
        : `Run 2 is past tick ${int(b.tick)}. Start it again and capture at tick ${int(b.tick)}.`;
    } else if (this.result === null) {
      hint = `Two separate runs captured at tick ${int(b.tick)}. Press Compare now.`;
    } else if (this.result === "identical") {
      hint = `IDENTICAL - PASS. Two separate runs produced the same trace hash at tick ${int(b.tick)}. The run is bit-for-bit reproducible from the seed.`;
    } else if (sameConfig(b.config, r.config)) {
      hint = `MISMATCH. Two runs of the same configuration diverged by tick ${int(b.tick)}; determinism is not holding for this configuration.`;
    } else {
      hint = `MISMATCH. The two runs used different configurations, so their hashes differ at tick ${int(b.tick)}.`;
    }
    box.innerHTML = `
      <div class="hashline" data-match="${match}">
        <span class="kv__k">Run 1</span><span class="num">${shortHash(b.hash)}</span>
      </div>
      <div class="field__hint">${describe(b)}</div>
      <div class="hashline" data-match="${match}">
        <span class="kv__k">Run 2</span><span class="num">${shortHash(r && r.hash)}</span>
      </div>
      ${r ? `<div class="field__hint">${describe(r)}</div>` : ""}
      <div class="field__hint">${hint}</div>`;
  }
}
