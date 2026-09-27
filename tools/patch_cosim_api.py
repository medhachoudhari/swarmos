"""Wire the X-12 co-simulation into the HTTP + WebSocket surface.

Touches app/api/server.py and web/js/transport.js together, because
tests/test_api.py::test_routes_match_frontend asserts the two are in lockstep:
every /api path the server serves must be called by transport.js (bar the two
allowed diagnostics), and the set of WS paths must match exactly. Patching one
file without the other would turn that test red by design.

Note on the WS parity check: its regex is WS_PATH\\s*=\\s*"([^"]+)", which also
matches COSIM_WS_PATH, so declaring the new socket as a const in transport.js is
what keeps the assertion satisfied.
"""

import ast
import pathlib
import subprocess

SERVER = pathlib.Path("app/api/server.py")
TRANSPORT = pathlib.Path("web/js/transport.js")


def sub(text, old, new, label):
    assert text.count(old) == 1, f"anchor not unique: {label}"
    return text.replace(old, new)


# ------------------------------------------------------------------ server.py

src = SERVER.read_text()

src = sub(
    src,
    """    POST /api/benchmark/run {scenario, seeds, ticks}
    WS   /ws/fleet
""",
    """    POST /api/benchmark/run {scenario, seeds, ticks}
    POST /api/cosim/start   {scenario, seed, fleet_size, ticks, speed,
                             integrity}
    POST /api/cosim/stop
    POST /api/cosim/inject  {fault}
    GET  /api/cosim/status
    WS   /ws/fleet
    WS   /ws/cosim
""",
    "docstring contract",
)

src = sub(
    src,
    """from app.api.runner import POLICIES, RunConfig, manager
from app.sim.scenarios import FaultKind, list_scenarios""",
    """from app.api.cosim_runner import CoSimConfig, cosim_manager
from app.api.runner import POLICIES, RunConfig, manager
from app.sim.scenarios import FaultKind, list_scenarios""",
    "imports",
)

# Handlers go in just before the read-only section banner.
src = sub(
    src,
    """# --------------------------------------------------------------------------
# read-only surfaces
# --------------------------------------------------------------------------
""",
    '''# --------------------------------------------------------------------------
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
''',
    "cosim handlers",
)

src = sub(
    src,
    """MAX_BENCH_SEEDS = 12
MAX_BENCH_TICKS = 3000""",
    """MAX_BENCH_SEEDS = 12
MAX_BENCH_TICKS = 3000

# Re-exported from the co-simulation manager so the HTTP layer and the manager
# cannot drift to different defaults. 1800 ticks is 180 s of sim time, which is
# past the startup transient; fleet 8 is the measured parity point.
COSIM_DEFAULT_TICKS = CoSimDefaults.ticks
COSIM_DEFAULT_FLEET = CoSimDefaults.fleet_size""",
    "cosim defaults",
)

src = sub(
    src,
    """    Route("/api/benchmark/run", benchmark_run, methods=["POST"]),
    WebSocketRoute("/ws/fleet", ws_fleet),""",
    """    Route("/api/benchmark/run", benchmark_run, methods=["POST"]),
    Route("/api/cosim/start", cosim_start, methods=["POST"]),
    Route("/api/cosim/stop", cosim_stop, methods=["POST"]),
    Route("/api/cosim/inject", cosim_inject, methods=["POST"]),
    Route("/api/cosim/status", cosim_status, methods=["GET"]),
    WebSocketRoute("/ws/fleet", ws_fleet),
    WebSocketRoute("/ws/cosim", ws_cosim),""",
    "route table",
)

# CoSimDefaults is just the dataclass defaults; name it at the import site.
src = sub(
    src,
    "from app.api.cosim_runner import CoSimConfig, cosim_manager",
    "from app.api.cosim_runner import CoSimConfig as CoSimDefaults\nfrom app.api.cosim_runner import CoSimConfig, cosim_manager",
    "CoSimDefaults alias",
)
src = sub(
    src,
    "COSIM_DEFAULT_TICKS = CoSimDefaults.ticks",
    "COSIM_DEFAULT_TICKS = CoSimDefaults().ticks",
    "ticks default call",
)
src = sub(
    src,
    "COSIM_DEFAULT_FLEET = CoSimDefaults.fleet_size",
    "COSIM_DEFAULT_FLEET = CoSimDefaults().fleet_size",
    "fleet default call",
)

ast.parse(src)
SERVER.write_text(src)
print("patched app/api/server.py")


# -------------------------------------------------------------- transport.js

js = TRANSPORT.read_text()

js = sub(
    js,
    'const WS_PATH = "/ws/fleet";',
    'const WS_PATH = "/ws/fleet";\n'
    '/* The co-simulation stream is a SECOND socket, not a message type on the\n'
    ' * first one. The live map must keep its steady 10 Hz while a comparison\n'
    ' * runs, and a client that wants only one of the two should not pay for\n'
    ' * both. */\n'
    'const COSIM_WS_PATH = "/ws/cosim";',
    "ws path const",
)

js = sub(
    js,
    '  benchmark(b)   { return this.post("/api/benchmark/run", b); }',
    '  benchmark(b)   { return this.post("/api/benchmark/run", b); }\n'
    '\n'
    '  /* ---- Co-simulation (X-12). No policy argument: the two arms ARE the\n'
    '   * policies, so naming one would allow a run against itself. ---- */\n'
    '  startCosim(cfg)   { return this.post("/api/cosim/start", cfg); }\n'
    '  stopCosim()       { return this.post("/api/cosim/stop", {}); }\n'
    '  injectCosim(f)    { return this.post("/api/cosim/inject", f); }\n'
    '  cosimStatus()     { return this.get("/api/cosim/status"); }\n'
    '  cosimSocketUrl()  {\n'
    '    const proto = location.protocol === "https:" ? "wss:" : "ws:";\n'
    '    return `${proto}//${location.host}${COSIM_WS_PATH}`;\n'
    '  }',
    "cosim REST surface",
)

TRANSPORT.write_text(js)
subprocess.run(["node", "--check", str(TRANSPORT)], check=True)
print("patched web/js/transport.js (node --check passed)")
