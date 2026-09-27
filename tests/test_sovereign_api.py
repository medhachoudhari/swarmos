"""X-01 across the HTTP and WebSocket boundary.

The unit tests in test_sovereign.py drive the engine directly. These drive the
product the way the operator does: POST the fault by its UI name, then read the
WebSocket frame the browser reads. That boundary is exactly where the first
version of this feature was broken -- the Lab's 'comm_blackout' name was
aliased to LINK_IMPAIR, so the fault the UI offered was not the fault the
backend implemented, and no unit test could have caught it.
"""
import time

import pytest
from starlette.testclient import TestClient

from app.api.runner import _FAULT_ALIASES
from app.api.server import app

FRAME_BUDGET = 150  # frames to wait for entry; ~15 s of sim time at 10 Hz


def test_ui_fault_names_are_distinct_kinds():
    """comm_blackout and link_impair must not collapse onto one kind.

    They model different physics: one robot deaf versus every link lossy.
    Aliasing them together would make the X-01 claim untestable from the UI.
    """
    assert _FAULT_ALIASES["comm_blackout"] == "COMM_BLACKOUT"
    assert _FAULT_ALIASES["link_impair"] == "LINK_IMPAIR"


def test_every_alias_names_a_real_fault_kind():
    from app.sim.scenarios import FaultKind

    known = {k.value for k in FaultKind}
    unknown = sorted(v for v in _FAULT_ALIASES.values() if v not in known)
    assert unknown == [], f"aliases point at kinds the engine does not have: {unknown}"


@pytest.mark.parametrize("seed", [11])
def test_blackout_over_the_api_reaches_sovereign_on_the_wire(seed):
    with TestClient(app) as client:
        started = client.post("/api/sim/start", json={
            "scenario": "rush_50", "fleet_size": 8, "seed": seed,
        })
        assert started.status_code == 200 and started.json()["ok"]
        try:
            # Let the run leave tick 0 so the fault lands on a live fleet.
            time.sleep(0.5)
            got = client.post("/api/sim/inject", json={"fault": "comm_blackout"})
            assert got.status_code == 200, got.text
            body = got.json()
            assert body["ok"], body
            assert body["fault"] == "COMM_BLACKOUT"
            assert body["detail"]["applied"] is True
            victim = body["detail"]["robot_id"]

            with client.websocket_connect("/ws/fleet") as ws:
                for _ in range(FRAME_BUDGET):
                    frame = ws.receive_json()
                    kpis = frame.get("kpis") or {}
                    if kpis.get("robots_sovereign"):
                        rows = {r["id"]: r for r in (frame.get("robots") or [])}
                        # The wire status is what the map colours on, so that is
                        # what the test asserts -- not an internal flag.
                        assert rows[victim]["s"] == "SOVEREIGN"
                        return
            pytest.fail(f"{victim} never appeared as SOVEREIGN in {FRAME_BUDGET} frames")
        finally:
            client.post("/api/sim/stop", json={})
