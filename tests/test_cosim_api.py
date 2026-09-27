"""Contract tests for the X-12 co-simulation HTTP + WebSocket surface.

Deliberately separate from tests/test_api.py: that file guards the LIVE fleet
surface, and mixing the two would make it unclear which manager a failure came
from. The live run and the co-simulation are separate managers on purpose (see
app/api/cosim_runner.py), so their tests stay separate too.

The speed multiplier is pushed high in these tests so a short horizon completes
in well under a second of wall time. It does not affect determinism: speed only
changes how long the loop sleeps between ticks, never what the engines compute.
"""

import pytest
from starlette.testclient import TestClient

import app.api.server as srv
from app.api.cosim_runner import cosim_manager
from app.sim.cosim import ARM_BASELINE, ARM_TREATMENT

FAST = 20.0


@pytest.fixture()
def client():
    cosim_manager.cosim = None
    cosim_manager.config = None
    cosim_manager.running = False
    cosim_manager._last_frame = None
    cosim_manager._summary = None
    with TestClient(srv.app) as c:
        yield c


def _start(c, **over):
    body = {"scenario": "rush_50", "seed": 11, "fleet_size": 6,
            "ticks": 20, "speed": FAST}
    body.update(over)
    return c.post("/api/cosim/start", json=body).json()


# ------------------------------------------------------------------ contract

def test_cosim_routes_are_served():
    paths = {getattr(r, "path", "") for r in srv.app.routes}
    for want in ("/api/cosim/start", "/api/cosim/stop", "/api/cosim/inject",
                 "/api/cosim/status", "/ws/cosim"):
        assert want in paths, f"route missing: {want}"


def test_status_is_honest_before_any_run(client):
    body = client.get("/api/cosim/status").json()
    assert body["ok"] is True
    assert body["has_run"] is False
    assert body["running"] is False
    # Not known yet must be None, never 0. The UI renders None as "--".
    assert body["tick"] is None
    assert body["summary"] is None


# --------------------------------------------------------------------- start

def test_start_accepts_a_config_and_reports_it_back(client):
    body = _start(client)
    assert body["ok"] is True
    assert body["config"]["scenario"] == "rush_50"
    assert body["config"]["fleet_size"] == 6
    assert body["config"]["ticks"] == 20


def test_start_rejects_an_unknown_scenario(client):
    body = _start(client, scenario="not_a_scenario")
    assert body["ok"] is False
    # The error text is rendered straight into the banner, so it must read as
    # a sentence that names the valid options.
    assert "rush_50" in body["error"]


def test_horizon_is_clamped_not_silently_accepted(client):
    body = _start(client, ticks=999999)
    assert body["ok"] is True
    assert body["config"]["ticks"] <= 3000


def test_start_has_no_policy_field(client):
    """The arms ARE the policies, so naming one must not be possible."""
    body = _start(client, policy="baseline")
    assert body["ok"] is True
    assert "policy" not in body["config"]


# ------------------------------------------------------------------- inject

def test_inject_without_a_run_is_refused(client):
    body = client.post("/api/cosim/inject", json={"fault": "ROGUE_ROBOT"}).json()
    assert body["ok"] is False
    assert "Start one first" in body["error"]


def test_inject_names_both_arms(client):
    _start(client)
    body = client.post("/api/cosim/inject", json={"fault": "ROGUE_ROBOT"}).json()
    assert body["ok"] is True
    # Both arms, always. A fault applied to one arm would rig the comparison.
    assert set(body["arms"]) == {ARM_TREATMENT, ARM_BASELINE}


def test_unnamed_fault_is_refused(client):
    _start(client)
    body = client.post("/api/cosim/inject", json={}).json()
    assert body["ok"] is False


# ---------------------------------------------------------------- websocket

def test_socket_sends_hello_even_with_no_run(client):
    with client.websocket_connect("/ws/cosim") as ws:
        hello = ws.receive_json()
    assert hello["type"] == "cosim_hello"
    assert hello["running"] is False
    assert hello["arms"] == [ARM_TREATMENT, ARM_BASELINE]


def test_socket_streams_two_arm_frames(client):
    _start(client, ticks=40)
    with client.websocket_connect("/ws/cosim") as ws:
        assert ws.receive_json()["type"] == "cosim_hello"
        frame = None
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "cosim":
                frame = msg
                break
        assert frame is not None, "no cosim frame arrived"

    assert set(frame["arms"]) == {ARM_TREATMENT, ARM_BASELINE}
    assert frame["lockstep"] is True
    assert frame["arms"][ARM_TREATMENT]["tick"] == frame["arms"][ARM_BASELINE]["tick"]
    # Two different policies must produce two different traces.
    assert (frame["arms"][ARM_TREATMENT]["trace_hash"]
            != frame["arms"][ARM_BASELINE]["trace_hash"])


def test_run_finishes_at_its_horizon_with_a_summary(client):
    _start(client, ticks=15)
    with client.websocket_connect("/ws/cosim") as ws:
        done = None
        for _ in range(60):
            msg = ws.receive_json()
            if msg["type"] == "cosim_done":
                done = msg
                break
        assert done is not None, "the run never reported completion"

    assert done["tick"] >= 15
    assert done["horizon_ticks"] == 15
    summary = done["summary"]
    # Both hashes present means the whole comparison is replayable.
    for arm in (ARM_TREATMENT, ARM_BASELINE):
        assert summary["arms"][arm]["trace_hash"]


# --------------------------------------------------------------- separation

def test_cosim_does_not_disturb_the_live_run_surface(client):
    """Architectural law 1: the live engine stays the single source of truth."""
    before = client.get("/api/status").json()
    _start(client)
    after = client.get("/api/status").json()
    assert before.get("has_run") == after.get("has_run")
    assert before.get("tick") == after.get("tick")


def test_stop_banks_the_summary(client):
    _start(client)
    assert client.post("/api/cosim/stop").json()["ok"] is True
    body = client.get("/api/cosim/status").json()
    assert body["running"] is False
    assert body["summary"] is not None
