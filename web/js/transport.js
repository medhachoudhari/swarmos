/* Transport: the WebSocket feed from M2, plus the REST control surface.
 *
 * Two design commitments here, both about honesty:
 *
 *  1. The link state is reported, never hidden. DEGRADED is a real state that
 *     the UI shows inline -- if frames are late the operator learns it from the
 *     product, not by noticing the map looks stale.
 *
 *  2. Reconnection is bounded exponential backoff with jitter, and every
 *     attempt is visible. A silent reconnect loop that never says "I gave up"
 *     is how a dashboard ends up confidently displaying last week's data.
 *
 * The fallback is explicit too: if no backend is reachable the UI does NOT
 * fabricate robots. It shows the empty state naming the cause and the action.
 */

import { store, LINK } from "./store.js";

const WS_PATH = "/ws/fleet";
/* The co-simulation stream is a SECOND socket, not a message type on the
 * first one. The live map must keep its steady 10 Hz while a comparison
 * runs, and a client that wants only one of the two should not pay for
 * both. */
const COSIM_WS_PATH = "/ws/cosim";
const API_BASE = "";              // same origin; M2 serves web/ statically
const STALE_MS = 700;             // 7 missed ticks at 10 Hz -> degraded
const BACKOFF_MS = [250, 500, 1000, 2000, 4000, 8000];
const MAX_ATTEMPTS = 12;

function apiError(data, status) {
  if (data && typeof data.error === "string" && data.error) return data.error;
  if (data && typeof data.detail === "string" && data.detail) return data.detail;
  return `The server rejected the request (HTTP ${status}).`;
}

export class Transport {
  constructor({ onBanner } = {}) {
    this.ws = null;
    this.attempt = 0;
    this.closedByUs = false;
    this.lastFrameAt = 0;
    this.onBanner = onBanner || (() => {});
    this._staleTimer = null;
  }

  url() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}${WS_PATH}`;
  }

  connect() {
    this.closedByUs = false;
    let ws;
    try {
      ws = new WebSocket(this.url());
    } catch (err) {
      this._scheduleReconnect(`WebSocket could not be created: ${err.message}`);
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      store.setLink(LINK.LIVE);
      this.onBanner(null);
      this._startStaleWatch();
    };

    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        // A malformed frame is dropped, loudly. It is never partially applied.
        console.warn("dropped malformed frame");
        return;
      }
      this.lastFrameAt = performance.now();
      if (store.link !== LINK.LIVE) store.setLink(LINK.LIVE);
      this._dispatch(msg);
    };

    ws.onclose = () => {
      this._stopStaleWatch();
      if (this.closedByUs) {
        store.setLink(LINK.DOWN);
        return;
      }
      this._scheduleReconnect("Connection to the coordination server closed.");
    };

    ws.onerror = () => {
      // onclose always follows, so the reconnect decision lives there only.
      store.setLink(LINK.DEGRADED);
    };
  }

  _dispatch(msg) {
    switch (msg.type) {
      case "hello":
        // Envelope discipline: schema_version is checked, not assumed.
        if (msg.schema_version && msg.schema_version !== "1.0") {
          this.onBanner({
            tone: "warn",
            cause: `Server speaks schema ${msg.schema_version}, this client speaks 1.0.`,
            action: "Fields may be missing. Reload after updating the client.",
          });
        }
        store.applyHello(msg);
        break;
      case "frame":
        store.applyFrame(msg);
        break;
      case "reset":
        store.reset();
        break;
      case "error":
        this.onBanner({
          tone: "error",
          cause: msg.cause || "The coordination server reported an error.",
          action: msg.action || "Check the server log, then restart the run.",
        });
        break;
      default:
        console.warn("unknown frame type", msg.type);
    }
  }

  /* A frame that is merely LATE is a different failure from a socket that is
   * CLOSED, and the operator needs to be able to tell them apart. */
  _startStaleWatch() {
    this._stopStaleWatch();
    this._staleTimer = setInterval(() => {
      // Never report staleness before the first frame has ever arrived: an
      // idle server that has not been given a run is not a late server.
      if (!this.lastFrameAt || !store.everFrame) return;
      // A deliberately PAUSED run stops sending frames on purpose - that is
      // not staleness, it is the feature working. Without this check, every
      // Pause looked exactly like a dead connection: the link flipped to
      // DEGRADED and the "no simulation frame" banner appeared within
      // STALE_MS of the operator's own Pause click.
      if (!store.running) return;
      const age = performance.now() - this.lastFrameAt;
      if (age > STALE_MS) {

        if (store.link === LINK.LIVE) {
          store.setLink(LINK.DEGRADED, `${Math.round(age)} ms since last frame`);
        }
        if (store.link === LINK.DEGRADED) {
          this._staleBannerOn = true;
          this.onBanner({
            tone: "warn",
            cause: `No simulation frame for ${Math.round(age)} ms (expected every 100 ms).`,
            action: "The map is showing the last known state. Coordination may be paused.",
          });
        }
      } else {
        // Frames are flowing again. applyFrame() may already have set the
        // link back to LIVE, so the clear must NOT be gated on DEGRADED or
        // it becomes unreachable and the banner latches on forever. The
        // ownership flag keeps us from clearing somebody else's banner
        // (a socket-closed or server-error banner must survive).
        if (store.link === LINK.DEGRADED) store.setLink(LINK.LIVE);
        if (this._staleBannerOn) {
          this._staleBannerOn = false;
          this.onBanner(null);
        }
      }
    }, 200);
  }

  _stopStaleWatch() {
    if (this._staleTimer) clearInterval(this._staleTimer);
    this._staleTimer = null;
    this._staleBannerOn = false;
  }

  _scheduleReconnect(cause) {
    store.setLink(LINK.DOWN);
    this.attempt += 1;
    if (this.attempt > MAX_ATTEMPTS) {
      this.onBanner({
        tone: "error",
        cause: `${cause} Gave up after ${MAX_ATTEMPTS} attempts.`,
        action: "Start the backend with ./run.sh, then press R to retry.",
      });
      return;
    }
    const base = BACKOFF_MS[Math.min(this.attempt - 1, BACKOFF_MS.length - 1)];
    const delay = base + Math.floor(Math.random() * 120);   // jitter
    this.onBanner({
      tone: "warn",
      cause,
      action: `Reconnecting in ${(delay / 1000).toFixed(1)} s (attempt ${this.attempt} of ${MAX_ATTEMPTS}).`,
    });
    setTimeout(() => this.connect(), delay);
  }

  retryNow() {
    this.attempt = 0;
    this.close();
    this.connect();
  }

  close() {
    this.closedByUs = true;
    this._stopStaleWatch();
    if (this.ws) this.ws.close();
    this.ws = null;
  }

  /* ---- REST control surface. Every call returns {ok, data, error} so the
   * caller never has to guess whether a failure was network or logic. ---- */

  /* The API reports a failure as {ok: false, error: "<human sentence>"}.
   * This used to read data.detail, which the server never sends, so every 4xx
   * in the product collapsed to a bare "HTTP 400" and threw away the one piece
   * of text that told the operator what to do about it. */
  async post(path, body) {
    try {
      const res = await fetch(`${API_BASE}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        return { ok: false, error: apiError(data, res.status), data };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: `Cannot reach the coordination server: ${err.message}` };
    }
  }

  async get(path) {
    try {
      const res = await fetch(`${API_BASE}${path}`);
      const data = await res.json().catch(() => null);
      if (!res.ok) {
        return { ok: false, error: apiError(data, res.status), data };
      }
      return { ok: true, data };
    } catch (err) {
      return { ok: false, error: `Cannot reach the coordination server: ${err.message}` };
    }
  }

  startRun(cfg)  { return this.post("/api/sim/start", cfg); }
  pauseRun()     { return this.post("/api/sim/pause", {}); }
  resumeRun()    { return this.post("/api/sim/resume", {}); }
  stopRun()      { return this.post("/api/sim/stop", {}); }
  stepRun(n)     { return this.post("/api/sim/step", { ticks: n || 1 }); }
  injectFault(f) { return this.post("/api/sim/inject", f); }
  scenarios()    { return this.get("/api/scenarios"); }
  traceHash()    { return this.get("/api/trace/hash"); }
  benchmark(b)   { return this.post("/api/benchmark/run", b); }

  /* ---- Co-simulation (X-12). No policy argument: the two arms ARE the
   * policies, so naming one would allow a run against itself. ---- */
  startCosim(cfg)   { return this.post("/api/cosim/start", cfg); }
  stopCosim()       { return this.post("/api/cosim/stop", {}); }
  injectCosim(f)    { return this.post("/api/cosim/inject", f); }
  cosimStatus()     { return this.get("/api/cosim/status"); }
  cosimSocketUrl()  {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}${COSIM_WS_PATH}`;
  }
}

// File contains AI-generated response based on internal company sources
