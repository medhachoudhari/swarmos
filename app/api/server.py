"""SWARMOS HTTP + WebSocket server (M2).

Written directly against Starlette, deliberately NOT FastAPI. The installed
pair in this environment is fastapi 0.104.1 against starlette 1.6.0, which is
incompatible (FastAPI passes `on_startup` into Router.__init__, which no longer
accepts it), and there is no network access to correct the versions. Raw
Starlette imports and runs cleanly, so that is what we build on. The cost is
that request bodies are validated by hand instead of by pydantic models; the
benefit is a server that actually starts.

Every JSON response carries an "ok" boolean. On failure it also carries an
"error" string written in plain language, because the browser renders that
string straight into the degraded banner - the user reads our error text, so
it has to be a sentence, not a stack trace fragment.

Route contract (must stay in lockstep with web/js/transport.js):

    POST /api/sim/start     {scenario, seed, fleet_size, policy, speed,
                             integrity}
    POST /api/sim/pause
    POST /api/sim/resume
    POST /api/sim/stop
    POST /api/sim/step      {ticks}
    POST /api/sim/inject    {fault, robot_id, count, zone}
    GET  /api/scenarios
    GET  /api/trace/hash
    GET  /api/status
    GET  /api/health
    POST /api/benchmark/run {scenario, seeds, ticks}
    POST /api/cosim/start   {scenario, seed, fleet_size, ticks, speed,
                             integrity}
    POST /api/cosim/stop
    POST /api/cosim/inject  {fault}
    GET  /api/cosim/status
    WS   /ws/fleet
    WS   /ws/cosim

Two HTML entry points are served:

    GET  /             web/landing.html   ROBONEX landing page  (state 1)
    GET  /index.html   web/index.html     SWARMOS dashboard     (states 2, 3)

"/" needs its own route because the StaticFiles mount resolves a bare "/" to
index.html by itself, which would skip the landing page entirely. The mount
still serves index.html and every other asset, so the dashboard URL is
unchanged and no simulation behaviour is touched.

tests/test_api.py asserts that contract mechanically in both directions so the
two files cannot drift apart silently.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect


from app.api.cosim_runner import CoSimConfig as CoSimDefaults
from app.api.cosim_runner import CoSimConfig, cosim_manager
from app.api.runner import POLICIES, RunConfig, manager
from app.sim.scenarios import FaultKind, list_scenarios

WEB_DIR = Path(__file__).resolve().parents[2] / "web"

# A benchmark is a genuinely long computation (ten seeds x two arms x 1800
# ticks). We cap what the HTTP surface will accept so a stray click cannot
# park a worker thread for an hour.
MAX_BENCH_SEEDS = 12
MAX_BENCH_TICKS = 3000

# Re-exported from the co-simulation manager so the HTTP layer and the manager
# cannot drift to different defaults. 1800 ticks is 180 s of sim time, which is
# past the startup transient; fleet 8 is the measured parity point.
COSIM_DEFAULT_TICKS = CoSimDefaults().ticks
COSIM_DEFAULT_FLEET = CoSimDefaults().fleet_size


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------

def _ok(payload: Optional[dict] = None) -> JSONResponse:
    body = {"ok": True}
    if payload:
        body.update(payload)
    return JSONResponse(body)


def _fail(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _relay(result: dict) -> JSONResponse:
    """Pass a RunManager result through, preserving its own ok/error verdict.

    The manager already decides whether an operation was legal and writes a
    readable reason when it was not. An earlier version of this file wrapped
    every manager result in _ok(), which silently turned "no run to pause"
    into an HTTP 200 carrying ok:false - so the browser saw success and the
    banner never appeared. The manager is the authority here; the transport
    layer only chooses the status code.
    """
    if result.get("ok"):
        return JSONResponse(result)
    return _fail(result.get("error", "The simulator rejected that request."))


async def _body(request: Request) -> dict:
    """Return the JSON body as a dict, or {} for an empty or non-object body.

    The control buttons post {} and we do not want an empty body to read as a
    client error, so absence is normalised rather than rejected.
    """
    try:
        raw = await request.body()
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        import json

        data = json.loads(raw)
    except Exception:
        raise ValueError("Request body was not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data


def _as_int(data: dict, key: str, default: Optional[int] = None) -> Optional[int]:
    if key not in data or data[key] is None:
        return default
    try:
        return int(data[key])
    except (TypeError, ValueError):
        raise ValueError(f"Field '{key}' must be a whole number.")


def _as_float(data: dict, key: str, default: Optional[float] = None):
    if key not in data or data[key] is None:
        return default
    try:
        return float(data[key])
    except (TypeError, ValueError):
        raise ValueError(f"Field '{key}' must be a number.")


def _as_str(data: dict, key: str, default: Optional[str] = None) -> Optional[str]:
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(f"Field '{key}' must be text.")
    value = value.strip()
    return value or default


# --------------------------------------------------------------------------
# simulation control
# --------------------------------------------------------------------------

async def sim_start(request: Request) -> JSONResponse:
    try:
        data = await _body(request)
        scenario = _as_str(data, "scenario") or ""
        seed = _as_int(data, "seed", 11)
        fleet = _as_int(data, "fleet_size", None)
        policy = (_as_str(data, "policy", "swarmos") or "swarmos").lower()
        speed = _as_float(data, "speed", 1.0)
        # Off unless asked for: the integrity layer changes nothing when off,
        # which is what keeps every previously recorded trace hash valid.
        integrity = bool(data.get("integrity", False))
    except ValueError as exc:
        return _fail(str(exc))

    known = {s["name"] for s in list_scenarios()}
    if scenario and scenario not in known:
        return _fail(
            f"Unknown scenario '{scenario}'. Choose one of: "
            + ", ".join(sorted(known))
            + "."
        )
    if policy not in POLICIES:
        return _fail(
            f"Unknown policy '{policy}'. Choose one of: " + ", ".join(POLICIES) + "."
        )

    cfg = RunConfig(
        scenario=scenario or list_scenarios()[0]["name"],
        seed=seed,
        fleet_size=fleet,
        policy=policy,
        speed=speed,
        integrity=integrity,
    )
    try:
        result = await manager.start(cfg)
    except Exception as exc:  # a bad scenario/fleet combination, say
        return _fail(f"Could not start the run: {exc}")
    return _relay(result)


async def sim_pause(request: Request) -> JSONResponse:
    return _relay(await manager.pause())


async def sim_resume(request: Request) -> JSONResponse:
    return _relay(await manager.resume())


async def sim_stop(request: Request) -> JSONResponse:
    return _relay(await manager.stop())


async def sim_step(request: Request) -> JSONResponse:
    try:
        data = await _body(request)
        ticks = _as_int(data, "ticks", 1) or 1
    except ValueError as exc:
        return _fail(str(exc))
    if ticks < 1:
        return _fail("Step count must be at least 1 tick.")
    # 100 ticks is ten seconds of sim time. Beyond that the request would
    # block the event loop long enough to look like a hang.
    ticks = min(ticks, 100)
    if not manager.has_run:
        return _fail("There is no run to step. Start a run first.")
    return _relay(await manager.step(ticks))


async def sim_inject(request: Request) -> JSONResponse:
    try:
        data = await _body(request)
        fault = _as_str(data, "fault")
    except ValueError as exc:
        return _fail(str(exc))
    if not fault:
        return _fail("No fault was named. Pick a fault to inject.")
    if not manager.has_run:
        return _fail("There is no run to inject into. Start a run first.")

    params: dict[str, Any] = {}
    for key in ("robot_id", "zone"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            params[key] = value.strip()
    if data.get("count") is not None:
        try:
            params["count"] = int(data["count"])
        except (TypeError, ValueError):
            return _fail("Field 'count' must be a whole number.")

    try:
        result = await manager.inject(fault, **params)
    except Exception as exc:
        return _fail(f"Could not inject '{fault}': {exc}")
    return _relay(result)


# --------------------------------------------------------------------------
# co-simulation (X-12)
# --------------------------------------------------------------------------

async def cosim_start(request: Request) -> JSONResponse:
    """Start a two-arm counterfactual run.

    There is no `policy` field on purpose. The arms ARE the policies - asking
    the caller to name one would let it start a co-simulation of a policy
    against itself, which would render two identical fleets and prove nothing.
    """
    try:
        data = await _body(request)
        scenario = _as_str(data, "scenario") or ""
        seed = _as_int(data, "seed", 11)
        fleet = _as_int(data, "fleet_size", COSIM_DEFAULT_FLEET)
        ticks = _as_int(data, "ticks", COSIM_DEFAULT_TICKS)
        speed = _as_float(data, "speed", 1.0)
        integrity = bool(data.get("integrity", False))
    except ValueError as exc:
        return _fail(str(exc))

    known = {s["name"] for s in list_scenarios()}
    if scenario and scenario not in known:
        return _fail(
            f"Unknown scenario '{scenario}'. Choose one of: "
            + ", ".join(sorted(known))
            + "."
        )
    if ticks is not None and ticks < 1:
        return _fail("The comparison horizon must be at least 1 tick.")

    cfg = CoSimConfig(
        scenario=scenario or list_scenarios()[0]["name"],
        seed=seed,
        fleet_size=fleet,
        ticks=ticks if ticks is not None else COSIM_DEFAULT_TICKS,
        speed=speed,
        integrity=integrity,
    )
    try:
        result = await cosim_manager.start(cfg)
    except Exception as exc:
        return _fail(f"Could not start the co-simulation: {exc}")
    return _relay(result)


async def cosim_stop(request: Request) -> JSONResponse:
    return _relay(await cosim_manager.stop())


async def cosim_inject(request: Request) -> JSONResponse:
    """Inject a fault into BOTH arms at the same tick.

    Single-arm injection is deliberately not offered. Faulting only the
    baseline would manufacture the result the comparison is supposed to test.
    """
    try:
        data = await _body(request)
        fault = _as_str(data, "fault")
    except ValueError as exc:
        return _fail(str(exc))
    if not fault:
        return _fail("No fault was named. Pick a fault to inject.")
    if not cosim_manager.has_run:
        return _fail("There is no co-simulation to inject into. Start one first.")
    return _relay(await cosim_manager.inject(fault))


async def cosim_status(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, **cosim_manager.status()})


async def ws_cosim(ws: WebSocket) -> None:
    """The co-simulation socket, separate from /ws/fleet.

    Two sockets rather than one multiplexed stream: the live map must keep
    receiving frames at a steady 10 Hz even while a co-simulation is running,
    and a client that only wants one of the two should not have to pay the
    bandwidth of both.
    """
    await ws.accept()
    queue = cosim_manager.subscribe()
    try:
        await ws.send_json(cosim_manager.hello_payload())
        last = cosim_manager.last_frame()
        if last is not None:
            await ws.send_json(last)
        while True:
            message = await queue.get()
            await ws.send_json(message)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except RuntimeError:
        pass
    finally:
        cosim_manager.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await ws.close()


# --------------------------------------------------------------------------
# read-only surfaces
# --------------------------------------------------------------------------

async def scenarios(request: Request) -> JSONResponse:
    return _ok(
        {
            "scenarios": list_scenarios(),
            "faults": [k.value for k in FaultKind],
            "policies": list(POLICIES),
        }
    )


async def trace_hash(request: Request) -> JSONResponse:
    return _ok(manager.trace_hash())


async def status(request: Request) -> JSONResponse:
    return _ok({"status": manager.status()})


async def health(request: Request) -> JSONResponse:
    return _ok({"service": "swarmos", "has_run": manager.has_run})


# --------------------------------------------------------------------------
# html entry points
# --------------------------------------------------------------------------

async def landing(request: Request):
    """Serve the ROBONEX landing page at "/".

    Falls back to the dashboard if landing.html is ever missing, so a partial
    checkout degrades into the working product rather than a 404.
    """
    page = WEB_DIR / "landing.html"
    if not page.is_file():
        page = WEB_DIR / "index.html"
    return FileResponse(str(page), media_type="text/html")


# --------------------------------------------------------------------------
# benchmark
# --------------------------------------------------------------------------

async def benchmark_run(request: Request) -> JSONResponse:
    from app.api.runner import _make_policy
    from app.db import benchmark as bench

    try:
        data = await _body(request)
        scenario = _as_str(data, "scenario") or list_scenarios()[0]["name"]
        ticks = _as_int(data, "ticks", 600) or 600
    except ValueError as exc:
        return _fail(str(exc))

    raw_seeds = data.get("seeds")
    if raw_seeds is None:
        seeds = tuple(bench.DEFAULT_SEEDS[:4])
    else:
        if not isinstance(raw_seeds, (list, tuple)):
            return _fail("Field 'seeds' must be a list of whole numbers.")
        try:
            seeds = tuple(int(s) for s in raw_seeds)
        except (TypeError, ValueError):
            return _fail("Field 'seeds' must be a list of whole numbers.")
    if not seeds:
        return _fail("At least one seed is required for a paired comparison.")
    if len(seeds) > MAX_BENCH_SEEDS:
        return _fail(
            f"At most {MAX_BENCH_SEEDS} seeds per request; this one asked for "
            f"{len(seeds)}."
        )
    ticks = max(60, min(ticks, MAX_BENCH_TICKS))

    def _work():
        return bench.run_ab(
            scenario,
            baseline_factory=lambda seed: _make_policy("baseline", seed),
            treatment_factory=lambda seed: _make_policy("swarmos", seed),
            seeds=seeds,
            ticks=ticks,
        )

    try:
        result = await asyncio.to_thread(_work)
    except Exception as exc:
        return _fail(f"Benchmark failed: {exc}")

    # Throughput is reported higher-is-better; completion time lower-is-better.
    # Both are surfaced because the honest story needs both.
    throughput = result.compare("tasks_per_min", lower_is_better=False)
    latency = result.compare("avg_completion_s", lower_is_better=True)
    return _ok(
        {
            "scenario": scenario,
            "ticks": ticks,
            "seeds": list(result.seeds),
            "usable_seeds": list(result.usable_seeds),
            "throughput": throughput.as_dict(),
            "latency": latency.as_dict(),
            "safety": result.safety_summary(),
            "report": throughput.render(),
        }
    )


# --------------------------------------------------------------------------
# websocket
# --------------------------------------------------------------------------

async def ws_fleet(ws: WebSocket) -> None:
    await ws.accept()
    queue = manager.subscribe()
    try:
        # hello goes out unconditionally, even with no run loaded. The browser
        # needs to distinguish "not connected" from "connected, nothing
        # running" so it can show its real empty state instead of a blank map.
        await ws.send_json(manager.hello_payload())
        last = manager.last_frame()
        if last is not None:
            # A client that joins mid-run should see the world immediately
            # rather than waiting up to 100 ms for the next tick.
            await ws.send_json(last)

        while True:
            message = await queue.get()
            await ws.send_json(message)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except RuntimeError:
        # Socket closed underneath us mid-send; nothing useful to do.
        pass
    finally:
        manager.unsubscribe(queue)
        with contextlib.suppress(Exception):
            await ws.close()


# --------------------------------------------------------------------------
# application
# --------------------------------------------------------------------------

routes = [
    Route("/api/sim/start", sim_start, methods=["POST"]),
    Route("/api/sim/pause", sim_pause, methods=["POST"]),
    Route("/api/sim/resume", sim_resume, methods=["POST"]),
    Route("/api/sim/stop", sim_stop, methods=["POST"]),
    Route("/api/sim/step", sim_step, methods=["POST"]),
    Route("/api/sim/inject", sim_inject, methods=["POST"]),
    Route("/api/scenarios", scenarios, methods=["GET"]),
    Route("/api/trace/hash", trace_hash, methods=["GET"]),
    Route("/api/status", status, methods=["GET"]),
    Route("/api/health", health, methods=["GET"]),
    Route("/api/benchmark/run", benchmark_run, methods=["POST"]),
    Route("/api/cosim/start", cosim_start, methods=["POST"]),
    Route("/api/cosim/stop", cosim_stop, methods=["POST"]),
    Route("/api/cosim/inject", cosim_inject, methods=["POST"]),
    Route("/api/cosim/status", cosim_status, methods=["GET"]),
    WebSocketRoute("/ws/fleet", ws_fleet),
    WebSocketRoute("/ws/cosim", ws_cosim),
    # Declared before the StaticFiles mount below, which would otherwise
    # resolve "/" to index.html and never reach the landing page.
    Route("/", landing, methods=["GET"]),
]

if WEB_DIR.is_dir():
    # Mounted LAST and only last: a catch-all mount at "/" placed any earlier
    # would shadow every /api and /ws route above it.
    routes.append(Mount("/", app=StaticFiles(directory=str(WEB_DIR), html=True)))

@contextlib.asynccontextmanager
async def lifespan(_app):
    """Stop the tick loop on shutdown.

    starlette 1.6 removed add_event_handler, so the lifespan context manager
    is the only supported hook. Without this, Ctrl-C leaves the simulation
    task running and uvicorn waits on it forever.
    """
    yield
    await manager.stop()


# CORS is needed for exactly one case: landing.html opened straight off disk
# (file://, origin "null") talking to this server over http. Every other
# client (the dashboard served BY this same process) is same-origin and never
# touches this middleware. allow_origins=["*"] is safe here specifically
# because the API has no cookies/session auth to leak - every route is a
# plain, unauthenticated JSON control surface for a local simulation demo.
middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        # Chrome's Private Network Access check: a page whose own origin is
        # "null" (file://) or otherwise public is, by Chrome's classification,
        # making a request to a PRIVATE address (127.0.0.1) - a separate check
        # from ordinary CORS, and it fails closed with no usable error message
        # beyond a generic CORS block unless this flag is also sent. Without
        # it, landing.html opened via file:// can never reach this server in
        # Chrome even though allow_origins=["*"] is otherwise satisfied.
        allow_private_network=True,
    ),
]


app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


# File contains AI-generated response based on internal company sources
