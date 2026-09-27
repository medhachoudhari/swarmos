/* X-12 counterfactual co-simulation client.
 *
 * This is a SECOND websocket, deliberately separate from the live fleet
 * socket. The live map must hold its steady 10 Hz whether or not a comparison
 * is running, and the co-simulation must be able to finish, reset or fall over
 * without touching the authoritative run.
 *
 * Architectural law 1 says the live simulation is the single source of truth
 * for robot state. A co-simulation is NOT that: it is two hypothetical worlds
 * neither of which is the fleet. So its robots never enter the store. They are
 * handed to the map as a clearly-labelled overlay, and the map draws them in
 * ink, never in state colour, so an operator can never mistake a hypothesis
 * for a robot that exists.
 *
 * Honesty gate: the baseline ghosts are only drawn when the co-simulation is
 * running the SAME scenario and the SAME seed as the live run. Two different
 * warehouses overlaid on one another would look like a comparison and be
 * nothing of the kind. When the gate is shut the panel says so and names the
 * fix, and no ghosts are drawn at all.
 */

import { adaptRobot } from "./store.js";

export const ARM_TREATMENT = "swarmos";
export const ARM_BASELINE = "baseline";

const RECONNECT_MS = 1000;

export class CosimClient {
  constructor(transport) {
    this.transport = transport;
    this.ws = null;
    this.listeners = new Set();

    this.running = false;
    this.config = null;          // echoed back by the server, never guessed
    this.tick = null;            // null, not 0, until a frame lands
    this.horizonTicks = null;
    this.lockstep = null;
    this.divergenceTick = null;
    this.summary = null;
    this.delta = [];
    this.hashes = { [ARM_TREATMENT]: null, [ARM_BASELINE]: null };
    this.compute = null;
    this.error = null;

    // Baseline arm robots, canonical form, plus the wall-clock instant the
    // frame arrived. The map needs both to interpolate between ticks.
    this.ghosts = [];
    this.ghostsPrev = new Map();   // robot_id -> {x, y}
    this.ghostsAt = 0;

    this._reconnect = null;
  }

  /* --------------------------------------------------------- subscribe --- */

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  _notify() {
    for (const fn of this.listeners) {
      try { fn(this); } catch (err) { console.error("cosim listener failed", err); }
    }
  }

  /* ------------------------------------------------------------ socket --- */

  connect() {
    if (this.ws) return;
    let ws;
    try {
      ws = new WebSocket(this.transport.cosimSocketUrl());
    } catch (err) {
      this.error = "Could not open the comparison stream.";
      this._notify();
      return;
    }
    this.ws = ws;

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (err) { return; }
      this._apply(msg);
      this._notify();
    };

    ws.onclose = () => {
      this.ws = null;
      // A closed comparison stream is not a degraded fleet, so it must never
      // raise the global banner. Retry quietly instead.
      if (this._reconnect) clearTimeout(this._reconnect);
      this._reconnect = setTimeout(() => this.connect(), RECONNECT_MS);
    };

    ws.onerror = () => { /* onclose handles recovery */ };
  }

  disconnect() {
    if (this._reconnect) { clearTimeout(this._reconnect); this._reconnect = null; }
    if (this.ws) { const w = this.ws; this.ws = null; w.close(); }
  }

  /* ------------------------------------------------------- frame apply --- */

  _apply(msg) {
    switch (msg.type) {
      case "cosim_hello":
        this.running = Boolean(msg.running);
        this.config = msg.config || null;
        this.horizonTicks = msg.horizon_ticks ?? null;
        break;

      case "cosim":
        this.running = true;
        this.error = null;
        this.tick = msg.tick ?? null;
        this.lockstep = msg.lockstep ?? null;
        this.divergenceTick = msg.divergence_tick ?? null;
        this.delta = Array.isArray(msg.delta) ? msg.delta : [];
        this.compute = msg.compute || null;
        this._applyArms(msg.arms || {});
        break;

      case "cosim_done":
        this.running = false;
        this.tick = msg.tick ?? this.tick;
        this.horizonTicks = msg.horizon_ticks ?? this.horizonTicks;
        this.summary = msg.summary || null;
        if (this.summary && this.summary.delta) this.delta = this.summary.delta;
        break;

      case "cosim_reset":
        this.running = false;
        this.ghosts = [];
        this.ghostsPrev.clear();
        this.summary = msg.summary || this.summary;
        break;

      default:
        break;
    }
  }

  _applyArms(arms) {
    for (const arm of [ARM_TREATMENT, ARM_BASELINE]) {
      const a = arms[arm];
      this.hashes[arm] = a && a.trace_hash ? a.trace_hash : null;
    }
    const base = arms[ARM_BASELINE];
    if (!base || !Array.isArray(base.robots)) return;

    const next = [];
    const seen = new Set();
    for (const raw of base.robots) {
      const r = adaptRobot(raw);
      const prev = this.ghostsPrev.get(r.robot_id);
      r.prevPosition = prev ? { x: prev.x, y: prev.y } : { x: r.position.x, y: r.position.y };
      this.ghostsPrev.set(r.robot_id, { x: r.position.x, y: r.position.y });
      seen.add(r.robot_id);
      next.push(r);
    }
    for (const id of [...this.ghostsPrev.keys()]) {
      if (!seen.has(id)) this.ghostsPrev.delete(id);
    }
    this.ghosts = next;
    this.ghostsAt = performance.now();
  }

  /* ---------------------------------------------------------- commands --- */

  async start(cfg) {
    const res = await this.transport.startCosim(cfg);
    if (!res.ok) { this.error = res.error || "The comparison would not start."; }
    else {
      this.error = null;
      this.config = res.data && res.data.config ? res.data.config : cfg;
      this.summary = null;
      this.delta = [];
      this.tick = null;
      this.running = true;
      this.horizonTicks = this.config ? this.config.ticks ?? null : null;
      this.connect();
    }
    this._notify();
    return res;
  }

  async stop() {
    const res = await this.transport.stopCosim();
    if (!res.ok) this.error = res.error || "The comparison would not stop.";
    this._notify();
    return res;
  }

  async inject(fault) {
    // A fault always lands on BOTH arms. Injecting into one would rig the
    // comparison, so the API does not offer it and neither does the UI.
    const res = await this.transport.injectCosim({ fault });
    if (!res.ok) this.error = res.error || "The fault was refused.";
    this._notify();
    return res;
  }

  /* ------------------------------------------------------------- gates --- */

  /* True only when the ghosts can be laid over the live map honestly: same
   * scenario, same seed, same warehouse. Anything else is two pictures. */
  comparableWith(liveScenario, liveSeed) {
    if (!this.config) return false;
    if (!this.ghosts.length) return false;
    if (liveScenario == null || liveSeed == null) return false;
    return this.config.scenario === liveScenario
      && Number(this.config.seed) === Number(liveSeed);
  }

  /* The map's ghost source. Returns null when there is nothing honest to
   * draw, which the map treats as "draw no ghosts at all". */
  ghostSource(liveScenario, liveSeed) {
    if (!this.comparableWith(liveScenario, liveSeed)) return null;
    return { robots: this.ghosts, at: this.ghostsAt };
  }
}
