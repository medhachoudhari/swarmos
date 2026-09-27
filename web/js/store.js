/* Client-side state mirror.
 *
 * Architectural law 1 says the M5 simulation is the SINGLE authoritative source
 * of robot state. This store therefore never computes robot state, never
 * integrates motion, and never invents a value to fill a gap. It mirrors what
 * arrived and it reports what is missing. If a field is absent the UI shows
 * "--", because a plausible-looking wrong number is worse than a blank.
 *
 * It is a plain observable: subscribe(fn) -> unsubscribe. No framework.
 */

export const LINK = { DOWN: "down", DEGRADED: "degraded", LIVE: "live" };

const STATES = [
  "MOVING", "BLOCKED", "WAITING", "CHARGING",
  "AVAILABLE", "FAILED", "QUARANTINED", "SOVEREIGN",
];

function emptyKpis() {
  return {
    tasks_complete: null,
    tasks_per_min: null,
    avg_completion_s: null,
    p95_completion_s: null,
    collisions: null,
    overlap_ticks: null,
    near_misses: null,
    verdicts: null,
    replans: null,
    compute: { p95_ms: null },
  };
}

/* The engine sends a COMPACT per-tick payload (id/x/y/h/v/b/s/t/p/tg/pv) to
 * keep the 10 Hz frame small at 50 robots. The rest of the UI speaks the
 * canonical vocabulary from app/coordination/models.py. This function is the
 * single place those two forms meet -- if the wire format ever changes, this
 * is the only code that has to change with it.
 */
export function adaptRobot(w) {
  if (w.position) return w; // already canonical (a replayed or test frame)
  const path = [];
  const flat = w.p || [];
  for (let i = 0; i + 1 < flat.length; i += 2) path.push({ x: flat[i], y: flat[i + 1] });
  return {
    robot_id: w.id,
    position: { x: w.x, y: w.y },
    heading: w.h,
    velocity: w.v,
    battery: w.b,
    status: w.s,
    current_task_id: w.t ?? null,
    payload_class: w.pc,
    speed_class: w.sc,
    rogue: Boolean(w.rogue),
    // Where the robot SAYS it is, when that differs from where it is. Null
    // for every honest robot, which is almost all of them - so the map can
    // treat a non-null value as the whole story on its own.
    claimed: Array.isArray(w.cl) ? { x: w.cl[0], y: w.cl[1] } : null,
    movement_intent: w.tg
      ? { target: { x: w.tg[0], y: w.tg[1] }, path, eta: null, path_version: w.pv ?? null }
      : null,
    path,
  };
}

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

  // Blocked cells stay in CELL coordinates: the renderer multiplies by
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
  };
}

class Store {
  constructor() {
    this.link = LINK.DOWN;
    this.tick = 0;
    this.simTime = 0.0;
    this.scenario = null;
    this.seed = null;
    this.running = false;

    /** @type {Map<string, object>} robot_id -> AMRState mirror */
    this.robots = new Map();
    /** @type {Map<string, object>} robot_id -> latest verdict */
    this.verdicts = new Map();
    /** @type {Array<object>} live conflicts, newest last */
    this.conflicts = [];
    /** Warehouse geometry, sent once on connect. Null until then. */
    this.warehouse = null;

    this.kpis = emptyKpis();

    /* Bounded history for the four analytics charts. 600 samples at 10 Hz is
     * one minute of trace -- enough to show a trend, small enough to never
     * become a memory leak during a long demo. */
    this.HISTORY_CAP = 600;
    this.history = {
      tasksPerMin: [],
      blockedCount: [],
      computeMs: [],
      msgsPerRobot: [],
    };

    this.selectedRobot = null;
    /* Conflict ids already pulsed. A conflict pulses ONCE at birth, then holds
     * a static ring -- a permanently animating map is noise, not information. */
    this.pulsed = new Set();

    this._subs = new Set();
    this._frameCount = 0;
    this._lastFrameAt = 0;
    /* Monotonic: true once ANY frame has ever arrived, and never cleared by
     * reset(). A cold start is not a degraded link, and the UI must be able to
     * tell those two apart before it accuses the backend of being stale. */
    this.everFrame = false;
  }

  subscribe(fn) {
    this._subs.add(fn);
    return () => this._subs.delete(fn);
  }

  _emit(reason) {
    for (const fn of this._subs) {
      try {
        fn(this, reason);
      } catch (err) {
        // A broken subscriber must not stall the 10 Hz feed.
        console.error("store subscriber failed", err);
      }
    }
  }

  setLink(link, detail) {
    if (this.link === link) return;
    this.link = link;
    this.linkDetail = detail || null;
    this._emit("link");
  }

  /** Geometry + scenario identity. Sent once per run, not per tick. */
  applyHello(msg) {
    this.warehouse = normaliseWarehouse(msg.warehouse);
    this.scenario = msg.scenario || null;
    this.seed = msg.seed ?? null;
    this._emit("hello");
  }

  /** One simulation tick. The only method that advances time. */
  applyFrame(msg) {
    this.tick = msg.tick ?? this.tick;
    this.simTime = msg.sim_time ?? this.simTime;
    this.running = msg.running ?? this.running;

    if (Array.isArray(msg.robots)) {
      // Replace-in-place so object identity is stable for the renderer's
      // interpolation, and so a robot missing from a frame is genuinely gone.
      const seen = new Set();
      for (const raw of msg.robots) {
        const r = adaptRobot(raw);
        seen.add(r.robot_id);
        const prev = this.robots.get(r.robot_id);
        if (prev) {
          prev.prevPosition = { x: prev.position.x, y: prev.position.y };
          Object.assign(prev, r);
        } else {
          r.prevPosition = { x: r.position.x, y: r.position.y };
          this.robots.set(r.robot_id, r);
        }
      }
      for (const id of [...this.robots.keys()]) {
        if (!seen.has(id)) this.robots.delete(id);
      }
    }

    if (Array.isArray(msg.verdicts)) {
      this.verdicts.clear();
      for (const v of msg.verdicts) this.verdicts.set(v.robot_id, v);
    }

    if (Array.isArray(msg.conflicts)) this.conflicts = msg.conflicts;

    if (msg.kpis) {
      // Merge rather than replace: a partial KPI payload must not blank the
      // rest of the strip.
      this.kpis = { ...this.kpis, ...msg.kpis };
      if (msg.kpis.compute) {
        this.kpis.compute = { ...this.kpis.compute, ...msg.kpis.compute };
      }
      this._pushHistory();
    }

    this._frameCount += 1;
    this.everFrame = true;
    this._emit("frame");
  }

  _pushHistory() {
    const k = this.kpis;
    const push = (arr, v) => {
      arr.push(v == null ? null : v);
      if (arr.length > this.HISTORY_CAP) arr.shift();
    };
    push(this.history.tasksPerMin, k.tasks_per_min);
    push(this.history.blockedCount, this.countByState().BLOCKED);
    push(this.history.computeMs, k.compute ? k.compute.p95_ms : null);
    push(this.history.msgsPerRobot, k.msgs_per_robot_tick ?? null);
  }

  countByState() {
    const out = Object.fromEntries(STATES.map((s) => [s, 0]));
    for (const r of this.robots.values()) {
      if (out[r.status] === undefined) out[r.status] = 0;
      out[r.status] += 1;
    }
    return out;
  }

  select(robotId) {
    if (this.selectedRobot === robotId) return;
    this.selectedRobot = robotId;
    this._emit("selection");
  }

  robot(id) {
    return this.robots.get(id) || null;
  }

  verdict(id) {
    return this.verdicts.get(id) || null;
  }

  /** True once real state has arrived. Gates every empty state in the UI. */
  get hasData() {
    return this.robots.size > 0;
  }

  reset() {
    this.robots.clear();
    this.verdicts.clear();
    this.conflicts = [];
    this.pulsed.clear();
    this.kpis = emptyKpis();
    for (const key of Object.keys(this.history)) this.history[key] = [];
    this.tick = 0;
    this.simTime = 0.0;
    this.selectedRobot = null;
    this._emit("reset");
  }
}

export const store = new Store();
export { STATES };
