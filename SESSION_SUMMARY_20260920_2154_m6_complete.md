# SWARMOS session summary - 2026-09-20 21:54 - M6 complete, 354/354 green

## State at checkpoint

Full suite: **354 passed in 18.40s**. Zero failures, zero skips.

```
cd /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920 && \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -m pytest tests/ -q
```

| Module | Status | Files | Tests |
|---|---|---|---|
| M5 simulation (`app/sim/`) | COMPLETE | clock, sensing, tasks, warehouse, robot, pathfinding, scenarios, policy, engine | 32 |
| M6 database + evidence (`app/db/`) | COMPLETE | schema, store, recorder, stats, benchmark, `__init__` | 26 |
| M4 coordination (`app/coordination/`) | pre-existing core only, Step 4B pending | models, messages, transport, peer_registry, intent_registry, reservation, conflict, auction | 296 |
| M2 API (`app/api/`) | not started | - | - |
| M1 frontend (`web/`) | not started | - | - |
| M3 ML (`app/ml/`) | not started | - | - |

## What was completed this session

### M5 driven to green - three fixes, all documented in code

1. **Symmetric arbitration wedged head-on traffic** (`app/sim/policy.py`).
   Judging each robot against every peer's full possible sweep made both robots
   in a head-on pair halt, so no one was privileged and the aisle never
   cleared - 33.4 halts/tick out of 50 robots, effective speed 0.38 m/s against
   1.2 nominal. Fixed by having an undecided peer contribute only its standing
   position to the reference geometry, so the lower-id robot takes right of way.
   Result: 0 -> 1 completion, 33.4 -> 30.8 halts/tick.

2. **REROUTE was a no-op** (`app/sim/engine.py`). A* knows about racks and
   blockages but not about the peer standing in the way, so "replan" returned
   the identical path - 974 reroutes, all useless. Fixed with `_avoid_hint`,
   populated from `verdict.conflict_with`, consumed once per replan (never a
   permanent grudge) with a fallback to the plain route when the detour is
   infeasible. Result: 1 -> 11 completions, 30.8 -> 16.7 halts/tick,
   reroutes 879 -> 438.

3. **13 collisions after a robot failure** (`app/sim/engine.py`). The arbiter
   cannot see FAILED robots by design - `observed_states()` withholds them, and
   that silence is the X-23 trigger - so live robots drove into the corpse.
   Fixed with `_apply_onboard_brake()`, a hardware bumper/LiDAR e-stop model
   that considers FAILED robots ONLY, so it cannot rescue a bad policy and the
   unarbitrated negative control still collides, plus
   `_invalidate_paths_near_failed()`.

### M6 built and verified

- `app/db/schema.py` - SCHEMA_VERSION 1, idempotent SQL for meta, runs,
  run_kpis, snapshots, events, task_records, violations, comparisons.
  SQLite over Postgres so the demo needs no service; snapshots stored sparsely
  so persistence never lands inside the 100 ms tick budget.
- `app/db/store.py` - `RunStore`, the only code allowed to touch SQLite.
  WAL, synchronous=NORMAL, git rev recorded per run, `msgs_per_robot_tick`
  derived from the run's own tick and fleet counts (X-03).
- `app/db/recorder.py` - newline-delimited JSON traces. NDJSON specifically so
  a `kill -9` leaves a readable prefix; `read_trace` reports `truncated` rather
  than pretending the run ended cleanly (X-27). `diff_traces` names the exact
  divergent tick; `verify_determinism` builds two independent engines rather
  than resetting one, because a reset could hide leaked state (X-22).
- `app/db/stats.py` - hardcoded t-table (no scipy dependency).
  `PairedComparison.verdict()` is the honesty gate: MET only when the LOWER
  bound of the 95% CI clears 20%, otherwise SIGNIFICANT_BELOW_TARGET,
  NOT_SIGNIFICANT or INSUFFICIENT_DATA.
- `app/db/benchmark.py` - `run_one`, `run_ab`, `message_scaling`. Both arms get
  the same seed, scenario, tick count and KPI code path; a seed on which either
  arm completed no tasks is excluded AND named.
- `app/db/__init__.py` - note the load-bearing import order: `benchmark.py`
  does `from app.db import stats`, so `stats` must be bound first.

### Two failures found and fixed while writing tests/test_db.py

- Real bug: `run_one` forwarded a `ScenarioSpec` object into
  `store.start_run(scenario=...)`, which SQLite cannot bind. Now resolves the
  name off the engine, so a spec built in code and a scenario name behave the
  same.
- Test was wrong, code was right: the first snapshot is tick 0, which is a
  decimation boundary, so 25 ticks at every=10 yields 3 rows (0, 10, 20) not 2.
  Keeping tick 0 is correct - a chart with no opening sample starts mid-air.

## Next step - M4 Step 4B, `app/coordination/`

Harden the existing normative core (do not casually change models.py,
messages.py, transport.py, peer_registry.py, intent_registry.py,
reservation.py, conflict.py, auction.py - they carry 296 passing tests):

1. X-09 safety monitor wiring - the binding arbiter verdict path.
2. X-18 graded verdict ladder (PROCEED / SLOW / YIELD / WAIT / REROUTE).
3. X-24 deterministic lock arbitration + `tests/test_race_condition.py`.
4. X-25 bounded radio, R_comm = 15 m, enforced at the transport seam.
5. X-02 link impairment injection.
6. X-23 failure detector (200 ms heartbeat gap) + gossip reservation GC.

Then Wave 2: X-01 Sovereign Agent Mode (multiprocessing behind
`transport.py`), X-10 rogue quarantine (HMAC-signed messages), X-12
counterfactual ghost fleet, X-20 advisory congestion forecaster.

Then M2 `app/api/`, M1 `web/`, M3 `app/ml/`, then the X-13 evidence run
(`run_ab` over the 10 published seeds), `run.sh`, README and the deck.

## Frozen conventions (unchanged)

Continuous 2-D metres; heading radians [0, 2pi), 0 = +X; velocity m/s >= 0;
battery 0-100%; 10 Hz tick, 100 ms budget; robot IDs R###, task IDs T###;
R_comm = 15 m; heartbeat 10 Hz, failure after 200 ms; envelope
schema_version "1.0"; M5 owns grid<->metre conversion.

Four architectural laws: M5 is the single authoritative source of robot state;
M4 is the binding safety arbiter; M3 is advisory only, never in the safety
path; one canonical model per concept in `app/coordination/models.py`.
