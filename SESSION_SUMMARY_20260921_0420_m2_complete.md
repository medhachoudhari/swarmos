# M2 complete: the stack runs end to end

Date: 2026-09-21 04:20 IST

## Status

| Gate | Result |
|---|---|
| Full pytest suite | **429 passed** in 18.2 s (was 407; +22 new, 0 regressions) |
| `tools/verify_frontend.py` | 10 js files, 43 html ids, 88 tokens, **0 errors / 0 warnings** |
| `tools/smoke_server.py` (real uvicorn) | **every check green** |

The browser can now load `/`, receive `hello`, stream 10 Hz frames over a real
websocket, and drive start / pause / resume / step / inject / trace-hash over
REST. M1 and M2 are joined.

## The blocker, and the decision

`fastapi 0.104.1` is installed against `starlette 1.6.0`. These are
incompatible: FastAPI passes `on_startup=` into `Router.__init__`, which
starlette 1.6 no longer accepts, so `FastAPI(...)` raises `TypeError` at import
time. `pip` cannot reach the network (`SSLCertVerificationError`), so neither
package can be moved.

**Decision: drop FastAPI and write `app/api/server.py` on raw Starlette.**
Raw Starlette imports and serves cleanly. The cost is hand-written request
validation instead of pydantic models. The benefit is a server that starts.
Starlette 1.6 also removed `add_event_handler`, so shutdown is a
`@contextlib.asynccontextmanager` `lifespan` passed to `Starlette(...)`.

## Four real defects the tests caught

These were found by writing the tests, not by reading the code. Each one would
have been visible on stage.

1. **`engine.tick` is a property, not a method.** Eight call sites in
   `runner.py` wrote `self.engine.tick()`, raising
   `TypeError: 'int' object is not callable` inside the tick loop. The run died
   the instant it started, and the error surfaced only as a 400 on `/start`.

2. **The server swallowed the manager's verdicts.** Every handler wrapped the
   `RunManager` result in `_ok(...)`, which turned `{"ok": false, "error":
   "No run to pause..."}` into an HTTP 200 carrying `ok:false`. The browser
   would have seen success and never raised the banner. Fixed with `_relay()`,
   which preserves the manager's own verdict and only chooses the status code.
   **The manager is the authority; the transport layer only translates.**

3. **`step()` refused while running.** It returned "Pause the run before
   stepping", so the UI's Step button was dead on a live run. A Step click on a
   live run is unambiguous - the operator wants the world frozen then advanced -
   so `step()` now auto-pauses. One click, not two.

4. **`stop()` leaked a dead run's frame to the next client.** `_last_frame` is
   kept during a run so a mid-run joiner sees the world immediately, but it
   survived `stop()`, so the next browser was served a stale frame from the
   finished run before the live one. The smoke test caught it as non-monotonic
   ticks: `[13, 0, 1, 2, 3]`. `stop()` now clears `_last_frame` while keeping
   the engine so the trace hash stays queryable.

Defect 4 is the one worth keeping in mind: it was invisible in-process and only
appeared over a real socket with a real reconnect. **In-process tests and a
real-transport smoke test are not substitutes for each other.**

## Two test bugs, honestly logged

Two initial failures were my test's premises being wrong, not the code's:
- "empty body on a control button is fine" posted to a manager with no run
  loaded, where refusing is correct. The test now starts a run first, and a
  second test asserts the refusal is readable.
- "step count is capped" asserted on the absolute tick counter, but the cap is
  per-request; `start()` has already emitted a frame. Now asserts the delta.

Also: `RunManager` is a module singleton and `stop()` deliberately keeps the
engine. Without an explicit reset the outcome of "pause with no run" depended on
test ordering, so the `client` fixture now resets the singleton's fields.

## Files

- `app/api/server.py` - rewritten on Starlette. 12 routes + static mount last.
- `app/api/runner.py` - 4 fixes (tick property x8, step auto-pause, stop clears
  the frame).
- `tests/test_api.py` - NEW, 22 tests.
- `tools/smoke_server.py` - NEW, real-socket end-to-end check.
- `tools/run_server.sh` - NEW. `tools/run_server.sh [port]`, default 8770.

## The contract test worth keeping

`test_routes_match_frontend` parses `web/js/transport.js` and asserts, in both
directions, that every path the browser calls is served and every `/api` path
served is called (allowing only `/api/status` and `/api/health` as
diagnostics). A client and server that disagree about a URL fail silently
during a demo; this fails loudly in CI instead.

## Next

M3 `app/ml/` - X-20 congestion forecaster, X-04 compute budget meter, firewall
veto counter. It must populate `verdict.advisory {kind, reason}` so the
Decision Inspector's Advisory -> Binding -> Applied chain renders real data and
architectural law 3 (ML is advisory only) becomes a visible rendering rather
than a claim.

## Unchanged and still binding

The measured performance story has not moved. Best-vs-best, both
collision-free: baseline 29 completions vs SWARMOS 21 = **-27.6%**. We do NOT
claim a throughput win. We lead with N3 deterministic replay, N5 Simplex
runtime assurance, N9 adversarial containment, N10 counterfactual
co-simulation, bounded-radio O(k) scaling, and the arbiter's perfect safety
record (zero collisions).
