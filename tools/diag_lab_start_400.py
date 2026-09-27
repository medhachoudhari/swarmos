"""Reproduce the HTTP 400 the Lab panel showed on Start.

The user had a live run (started by run.sh --demo) and then pressed Start in
the Lab tab with a different scenario and fleet size. The panel printed a bare
"HTTP 400". This script asks the real app what that 400 actually says.
"""
from starlette.testclient import TestClient

from app.api.server import app

with TestClient(app) as c:
    print("start #1 :", c.post("/api/sim/start",
                               json={"scenario": "rush_50", "seed": 11,
                                     "fleet_size": 8}).status_code)
    r2 = c.post("/api/sim/start", json={"scenario": "blocked_aisle",
                                        "seed": 11, "fleet_size": 30})
    print("start #2 :", r2.status_code, r2.json())
    r3 = c.post("/api/sim/step", json={"ticks": 1})
    print("step     :", r3.status_code, r3.json())
    c.post("/api/sim/stop")
    r4 = c.post("/api/sim/start", json={"scenario": "blocked_aisle",
                                        "seed": 11, "fleet_size": 30})
    print("after stop:", r4.status_code, str(r4.json())[:200])
    c.post("/api/sim/stop")
