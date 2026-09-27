"""SWARMOS M6 - the database schema, in one place.

Design decisions and the reasons for them, because a schema is a contract and
an undocumented contract gets violated:

  SQLite, not Postgres. The demo must start from a clean checkout on a laptop
  with no service to install and no port to argue about, and the entire dataset
  is a few megabytes of run history. A heavier database would add operational
  risk to the live demo and buy nothing.

  Runs are immutable once finished. A run row records what happened; it is
  never edited to make a later chart nicer. Deriving every reported number from
  these rows is what lets the same figure appear on screen and in the report.

  Snapshots are stored SPARSELY, not every tick. At 10 Hz a five-minute run is
  3000 ticks per fleet, and writing all of them makes SQLite the bottleneck
  inside the 100 ms budget - the persistence layer must never be the reason we
  miss real time. The full fidelity record is the trace file (recorder.py); the
  database keeps a decimated series for charts plus every discrete event.

  Times are stored as REAL seconds of simulation time, not wall-clock, because
  every comparison in this project is between runs that never happened at the
  same moment.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# Every statement is idempotent, so open() can run them unconditionally on an
# existing file without a migration step.
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per simulation run. label distinguishes the arms of an A/B
-- ("swarmos" vs "baseline") and policy records which arbiter actually drove it,
-- so a mislabelled run can always be caught after the fact.
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    started_utc   TEXT NOT NULL,
    finished_utc  TEXT,
    scenario      TEXT NOT NULL,
    label         TEXT NOT NULL,
    policy        TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    fleet_size    INTEGER NOT NULL,
    ticks         INTEGER NOT NULL DEFAULT 0,
    sim_time_s    REAL    NOT NULL DEFAULT 0,
    trace_hash    TEXT,
    git_rev       TEXT,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_scenario_seed
    ON runs (scenario, seed, label);

-- Final KPIs, one row per run. Columns rather than a JSON blob for the numbers
-- that appear in the published claims, because those must be queryable and
-- type-checked; the long tail stays in kpi_json.
CREATE TABLE IF NOT EXISTS run_kpis (
    run_id            TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
    tasks_complete    INTEGER NOT NULL,
    tasks_per_min     REAL    NOT NULL,
    avg_completion_s  REAL,
    p95_completion_s  REAL,
    avg_wait_s        REAL,
    collisions        INTEGER NOT NULL,
    near_misses       INTEGER NOT NULL,
    sla_miss_pct      REAL    NOT NULL,
    replans           INTEGER NOT NULL,
    messages_total    INTEGER NOT NULL DEFAULT 0,
    msgs_per_robot_tick REAL  NOT NULL DEFAULT 0,
    compute_p95_ms    REAL,
    compute_max_ms    REAL,
    kpi_json          TEXT NOT NULL
);

-- Decimated time series for the analytics charts.
CREATE TABLE IF NOT EXISTS snapshots (
    run_id         TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tick           INTEGER NOT NULL,
    sim_time_s     REAL    NOT NULL,
    tasks_complete INTEGER NOT NULL,
    tasks_pending  INTEGER NOT NULL,
    robots_moving  INTEGER NOT NULL,
    robots_waiting INTEGER NOT NULL,
    collisions     INTEGER NOT NULL,
    compute_ms     REAL    NOT NULL,
    PRIMARY KEY (run_id, tick)
);

-- Every discrete event, undecimated. These are cheap, rare and are the
-- evidence behind the fault-recovery story, so they are never sampled away.
CREATE TABLE IF NOT EXISTS events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tick       INTEGER NOT NULL,
    sim_time_s REAL    NOT NULL,
    kind       TEXT    NOT NULL,
    payload    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events (run_id, kind);

-- One row per completed task. This is the population the completion-time
-- statistics are computed over, kept per task rather than pre-aggregated so a
-- reviewer can recompute the mean and the CI from source.
CREATE TABLE IF NOT EXISTS task_records (
    run_id        TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id       TEXT NOT NULL,
    priority      TEXT NOT NULL,
    payload_kg    REAL NOT NULL,
    robot_id      TEXT,
    created_s     REAL NOT NULL,
    assigned_s    REAL,
    picked_s      REAL,
    completed_s   REAL,
    completion_s  REAL,
    wait_s        REAL,
    late          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, task_id)
);

-- Safety violations, stored in full. The table is expected to be empty; that
-- is the point. An empty table with a real writer behind it is evidence, and a
-- counter that was never wired up is not.
CREATE TABLE IF NOT EXISTS violations (
    run_id     TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    tick       INTEGER NOT NULL,
    sim_time_s REAL NOT NULL,
    robot_a    TEXT NOT NULL,
    robot_b    TEXT NOT NULL,
    distance_m REAL NOT NULL
);

-- Results of a multi-seed paired A/B. Stored so the headline number in the UI
-- is read back from the same row the report was generated from.
CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id TEXT PRIMARY KEY,
    created_utc   TEXT NOT NULL,
    scenario      TEXT NOT NULL,
    metric        TEXT NOT NULL,
    seeds         INTEGER NOT NULL,
    baseline_mean REAL NOT NULL,
    treatment_mean REAL NOT NULL,
    improvement_pct REAL NOT NULL,
    ci95_low_pct  REAL NOT NULL,
    ci95_high_pct REAL NOT NULL,
    status        TEXT NOT NULL,
    detail_json   TEXT NOT NULL
);
"""
# File contains AI-generated response based on internal company sources
