"""M2 route-contract and behaviour tests.

The most valuable assertion in this file is not any single endpoint check, it
is test_routes_match_frontend: it reads web/js/transport.js and asserts that
every path the browser calls is actually served, and that every /api path we
serve is actually called. A server and a client that disagree about a URL fail
silently at 3 a.m. during a demo; here it fails loudly in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.api import server as srv

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_JS = ROOT / "web" / "js" / "transport.js"


@pytest.fixture()
def client():
    """A test client over a manager reset to its just-imported state.

    RunManager is a module singleton and stop() deliberately KEEPS the engine
    so the trace hash survives the run it describes. That is right for the
    product and wrong for tests: without an explicit reset here, whether
    "pause with no run" refuses depends on which test ran before it. Resetting
    the fields directly makes every test order-independent.
    """
    import anyio

    anyio.run(srv.manager.stop)
    srv.manager.engine = None
    srv.manager.config = None
    srv.manager.running = False
    srv.manager._last_frame = None

    with TestClient(srv.app) as c:
        yield c

    anyio.run(srv.manager.stop)


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

def _served_paths() -> tuple[set[str], set[str]]:
    http, ws = set(), set()
    for route in srv.app.routes:
        path = getattr(route, "path", None)
        if not path or not path.startswith(("/api", "/ws")):
            continue
        if getattr(route, "methods", None):
            http.add(path)
        else:
            ws.add(path)
    return http, ws


def _frontend_paths() -> tuple[set[str], set[str]]:
    text = TRANSPORT_JS.read_text()
    http = set(re.findall(r'\.(?:post|get)\(\s*"(/api[^"]*)"', text))
    ws = set(re.findall(r'WS_PATH\s*=\s*"([^"]+)"', text))
    return http, ws


def test_routes_match_frontend():
    served_http, served_ws = _served_paths()
    want_http, want_ws = _frontend_paths()

    missing = want_http - served_http
    assert not missing, f"frontend calls paths the server does not serve: {missing}"
    assert want_ws == served_ws, f"websocket path mismatch: {want_ws} vs {served_ws}"

    # Extra server paths are allowed only for the diagnostics the UI does not
    # need. Anything else is dead code or a typo.
    allowed_extra = {"/api/status", "/api/health"}
    extra = served_http - want_http - allowed_extra
    assert not extra, f"server serves paths nothing calls: {extra}"


def test_static_mount_is_last():
    paths = [getattr(r, "path", "") for r in srv.app.routes]
    if "" in paths or "/" in paths:
        catchall = max(i for i, p in enumerate(paths) if p in ("", "/"))
        assert catchall == len(paths) - 1, "static mount must be the final route"


# --------------------------------------------------------------------------
# read-only surfaces
# --------------------------------------------------------------------------

def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["service"] == "swarmos"


def test_scenarios_lists_everything_the_lab_panel_needs(client):
    body = client.get("/api/scenarios").json()
    assert body["ok"] is True
    names = {s["name"] for s in body["scenarios"]}
    assert {"rush_50", "narrow_aisle_deadlock", "blocked_aisle"} <= names
    assert "robot_failure" in body["faults"] or "ROBOT_FAILURE" in body["faults"]
    assert set(body["policies"]) == {"swarmos", "baseline"}


def test_status_before_any_run(client):
    body = client.get("/api/status").json()
    assert body["ok"] is True
    assert body["status"]["running"] is False


# --------------------------------------------------------------------------
# validation: errors must be sentences, not tracebacks
# --------------------------------------------------------------------------

def test_unknown_scenario_is_rejected_with_a_readable_error(client):
    r = client.post("/api/sim/start", json={"scenario": "not_a_place"})
    assert r.status_code == 400
    error = r.json()["error"]
    assert "not_a_place" in error
    assert error.endswith(".")
    assert "rush_50" in error  # tells the user what IS valid


def test_unknown_policy_is_rejected(client):
    r = client.post("/api/sim/start", json={"scenario": "rush_50", "policy": "magic"})
    assert r.status_code == 400
    assert "magic" in r.json()["error"]


def test_bad_types_are_rejected(client):
    r = client.post("/api/sim/start", json={"seed": "not-a-number"})
    assert r.status_code == 400
    assert "seed" in r.json()["error"]


def test_step_without_a_run_explains_what_to_do(client):
    r = client.post("/api/sim/step", json={"ticks": 5})
    assert r.status_code == 400
    assert "Start a run" in r.json()["error"]


def test_inject_without_a_fault_name(client):
    r = client.post("/api/sim/inject", json={})
    assert r.status_code == 400
    assert "fault" in r.json()["error"].lower()


def test_empty_body_on_a_control_button_is_fine(client):
    # The control buttons post no body at all. Against a live run that must be
    # accepted; an absent body is not a malformed body.
    client.post("/api/sim/start", json={"scenario": "rush_50", "fleet_size": 4})
    for path in ("/api/sim/pause", "/api/sim/resume", "/api/sim/stop"):
        r = client.post(path)
        assert r.status_code == 200, path
        assert r.json()["ok"] is True, path


def test_controls_refuse_politely_when_there_is_no_run(client):
    # And with no run loaded they must refuse with a readable reason rather
    # than reporting a success the UI would believe.
    for path in ("/api/sim/pause", "/api/sim/resume"):
        r = client.post(path)
        assert r.status_code == 400, path
        assert "Start a scenario" in r.json()["error"], path


# --------------------------------------------------------------------------
# run lifecycle
# --------------------------------------------------------------------------

def test_start_step_stop(client):
    r = client.post(
        "/api/sim/start",
        json={"scenario": "rush_50", "seed": 11, "fleet_size": 6, "speed": 0.0},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    before = client.get("/api/status").json()["status"]["tick"]
    r = client.post("/api/sim/step", json={"ticks": 5})
    assert r.status_code == 200, r.text
    after = client.get("/api/status").json()["status"]["tick"]
    assert after >= before + 5

    assert client.post("/api/sim/stop").json()["ok"] is True


def test_fleet_size_is_clamped_not_rejected(client):
    r = client.post(
        "/api/sim/start", json={"scenario": "rush_50", "fleet_size": 9999}
    )
    assert r.status_code == 200, r.text
    fleet = client.get("/api/status").json()["status"]
    # RunConfig.normalised clamps to 50; a silly number should not 500.
    assert fleet["config"]["fleet_size"] <= 50


def test_step_count_is_capped(client):
    client.post("/api/sim/start", json={"scenario": "rush_50", "fleet_size": 4})
    before = client.get("/api/status").json()["status"]["tick"]
    r = client.post("/api/sim/step", json={"ticks": 100000})
    assert r.status_code == 200
    after = client.get("/api/status").json()["status"]["tick"]
    # The cap is on how many ticks ONE request may advance, not on the absolute
    # tick counter - start() has already produced a frame by this point.
    assert after - before <= 100


def test_inject_a_fault_into_a_live_run(client):
    client.post("/api/sim/start", json={"scenario": "rush_50", "fleet_size": 8})
    client.post("/api/sim/step", json={"ticks": 3})
    r = client.post("/api/sim/inject", json={"fault": "blocked_aisle"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_unknown_fault_is_rejected_readably(client):
    client.post("/api/sim/start", json={"scenario": "rush_50", "fleet_size": 4})
    r = client.post("/api/sim/inject", json={"fault": "alien_invasion"})
    assert r.status_code == 400
    assert "alien_invasion" in r.json()["error"]


# --------------------------------------------------------------------------
# N3 determinism receipt, over HTTP
# --------------------------------------------------------------------------

def test_trace_hash_is_reproducible_across_two_identical_runs(client):
    def run_and_hash() -> str:
        client.post(
            "/api/sim/start",
            json={"scenario": "rush_50", "seed": 11, "fleet_size": 8},
        )
        client.post("/api/sim/step", json={"ticks": 20})
        body = client.get("/api/trace/hash").json()
        assert body["ok"] is True
        client.post("/api/sim/stop")
        return body.get("hash") or body.get("trace_hash")

    first = run_and_hash()
    second = run_and_hash()
    assert first, "no hash was returned"
    assert first == second, "same scenario and seed produced different traces"


def test_different_seeds_diverge(client):
    def run_and_hash(seed: int) -> str:
        client.post(
            "/api/sim/start",
            json={"scenario": "rush_50", "seed": seed, "fleet_size": 8},
        )
        client.post("/api/sim/step", json={"ticks": 20})
        body = client.get("/api/trace/hash").json()
        client.post("/api/sim/stop")
        return body.get("hash") or body.get("trace_hash")

    assert run_and_hash(11) != run_and_hash(29)


# --------------------------------------------------------------------------
# websocket envelopes
# --------------------------------------------------------------------------

def test_ws_sends_hello_even_with_no_run(client):
    # The UI must be able to tell "connected but idle" from "disconnected",
    # which is only possible if hello arrives unconditionally.
    with client.websocket_connect("/ws/fleet") as ws:
        hello = ws.receive_json()
    assert hello["type"] == "hello"
    assert hello["schema_version"] == "1.0"
    assert hello["tick_hz"] == 10
    assert hello["running"] is False


def test_ws_replays_the_current_frame_to_a_late_joiner(client):
    client.post(
        "/api/sim/start",
        json={"scenario": "rush_50", "seed": 11, "fleet_size": 6, "speed": 0.0},
    )
    client.post("/api/sim/step", json={"ticks": 4})
    with client.websocket_connect("/ws/fleet") as ws:
        hello = ws.receive_json()
        frame = ws.receive_json()
    client.post("/api/sim/stop")

    assert hello["type"] == "hello"
    assert frame["type"] == "frame"
    assert frame["schema_version"] == "1.0"
    assert frame["tick"] >= 1
    assert frame["robots"], "a frame with no robots is not a frame"


def test_frame_robots_use_the_compact_wire_keys(client):
    client.post(
        "/api/sim/start",
        json={"scenario": "rush_50", "seed": 11, "fleet_size": 6, "speed": 0.0},
    )
    client.post("/api/sim/step", json={"ticks": 2})
    with client.websocket_connect("/ws/fleet") as ws:
        ws.receive_json()
        frame = ws.receive_json()
    client.post("/api/sim/stop")

    robot = frame["robots"][0]
    # store.js adaptRobot() is written against exactly this key set.
    for key in ("id", "x", "y", "h", "v", "b", "s", "p", "tg", "pv"):
        assert key in robot, f"wire frame is missing '{key}'"
