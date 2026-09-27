"""SWARMOS M6 - the persistence API.

One class, RunStore, is the only thing in the project allowed to touch SQLite.
Everything else - the API, the benchmark harness, the report generator - goes
through it, so the write path is auditable in a single file.

Two rules govern this module and both exist because the persistence layer sits
inside a hard real-time loop:

  Never block the tick. record_snapshot() decimates by default and commits on a
  timer, not per row. A synchronous fsync at 10 Hz would eat a large slice of
  the 100 ms budget and make the real-time claim depend on the speed of the
  disk, which is not a property of the coordination design.

  Never lie about what was measured. No column is computed twice: the KPI row
  is written straight from SimEngine.kpis(), so the number in the database, on
  screen and in the report is the same number by construction rather than by
  three consistent implementations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.db.schema import SCHEMA_SQL, SCHEMA_VERSION

DEFAULT_DB_PATH = "data/swarmos.db"

# Store one snapshot per this many ticks. 10 gives one sample per simulated
# second, which is more than enough resolution for a chart that is at most a
# few hundred pixels wide, and it cuts the write volume by 90%.
SNAPSHOT_EVERY = 10

# Commit at most this often, in seconds of wall time.
COMMIT_INTERVAL_S = 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git_rev() -> Optional[str]:
    """Short commit hash, or None outside a repository.

    Recorded on every run so a result can always be traced back to the exact
    code that produced it. A benchmark number without a revision is not
    reproducible, it is just a number.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        rev = out.stdout.strip()
        return rev or None
    except (OSError, subprocess.SubprocessError):
        return None


class RunStore:
    """SQLite-backed store for runs, snapshots, events and comparisons."""

    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)

        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # WAL lets the API read while a benchmark writes, which is what makes
        # the live Analytics panel usable during a run.
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        # NORMAL rather than FULL: a lost final transaction after a hard power
        # cut costs us one simulated run we can trivially re-run from its seed,
        # whereas FULL costs an fsync on the critical path of every commit.
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()
        self._last_commit = time.monotonic()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _maybe_commit(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if force or (now - self._last_commit) >= COMMIT_INTERVAL_S:
            self.conn.commit()
            self._last_commit = now

    # ------------------------------------------------------------------
    # runs
    # ------------------------------------------------------------------
    def start_run(
        self,
        *,
        scenario: str,
        label: str,
        policy: str,
        seed: int,
        fleet_size: int,
        notes: str = "",
        run_id: Optional[str] = None,
    ) -> str:
        """Open a run row and return its id."""
        rid = run_id or f"{label}-{scenario}-s{seed}-{uuid.uuid4().hex[:8]}"
        self.conn.execute(
            """
            INSERT INTO runs (run_id, started_utc, scenario, label, policy,
                              seed, fleet_size, git_rev, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (rid, _utc_now(), scenario, label, policy, int(seed),
             int(fleet_size), _git_rev(), notes),
        )
        self._maybe_commit(force=True)
        return rid

    def finish_run(
        self,
        run_id: str,
        *,
        ticks: int,
        sim_time_s: float,
        trace_hash: str,
        kpis: dict,
        messages_total: int = 0,
    ) -> None:
        """Close the run and write its final KPI row.

        msgs_per_robot_tick is derived here rather than stored raw because it is
        the X-03 scalability claim: if it stays flat as the fleet grows, message
        complexity really is O(k) and not O(N^2). Computing it from the same
        tick and fleet counts the run actually used stops the denominator from
        being quietly wrong.
        """
        compute = kpis.get("compute") or {}
        robots = max(1, int(kpis.get("robots_total") or 1))
        denom = max(1, ticks) * robots

        self.conn.execute(
            """
            UPDATE runs SET finished_utc = ?, ticks = ?, sim_time_s = ?,
                            trace_hash = ?
            WHERE run_id = ?
            """,
            (_utc_now(), int(ticks), float(sim_time_s), trace_hash, run_id),
        )
        self.conn.execute(
            """
            INSERT OR REPLACE INTO run_kpis (
                run_id, tasks_complete, tasks_per_min, avg_completion_s,
                p95_completion_s, avg_wait_s, collisions, near_misses,
                sla_miss_pct, replans, messages_total, msgs_per_robot_tick,
                compute_p95_ms, compute_max_ms, kpi_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                int(kpis.get("tasks_complete", 0)),
                float(kpis.get("tasks_per_min", 0.0)),
                kpis.get("avg_completion_s"),
                kpis.get("p95_completion_s"),
                kpis.get("avg_wait_s"),
                int(kpis.get("collisions", 0)),
                int(kpis.get("near_misses", 0)),
                float(kpis.get("sla_miss_pct", 0.0)),
                int(kpis.get("replans", 0)),
                int(messages_total),
                round(messages_total / denom, 6),
                compute.get("p95_ms"),
                compute.get("max_ms"),
                json.dumps(kpis, sort_keys=True),
            ),
        )
        self._maybe_commit(force=True)

    def get_run(self, run_id: str) -> Optional[dict]:
        row = self.conn.execute(
            """
            SELECT r.*, k.tasks_complete, k.tasks_per_min, k.avg_completion_s,
                   k.p95_completion_s, k.avg_wait_s, k.collisions,
                   k.near_misses, k.sla_miss_pct, k.replans,
                   k.msgs_per_robot_tick, k.compute_p95_ms, k.compute_max_ms
            FROM runs r LEFT JOIN run_kpis k USING (run_id)
            WHERE r.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_runs(
        self, *, scenario: Optional[str] = None, label: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = [
            "SELECT r.run_id, r.scenario, r.label, r.policy, r.seed, r.ticks,",
            "       r.sim_time_s, r.trace_hash, r.started_utc,",
            "       k.tasks_complete, k.tasks_per_min, k.avg_completion_s,",
            "       k.collisions",
            "FROM runs r LEFT JOIN run_kpis k USING (run_id)",
        ]
        where, args = [], []
        if scenario:
            where.append("r.scenario = ?")
            args.append(scenario)
        if label:
            where.append("r.label = ?")
            args.append(label)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY r.started_utc DESC LIMIT ?")
        args.append(int(limit))
        rows = self.conn.execute("\n".join(sql), args).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # per-tick data
    # ------------------------------------------------------------------
    def record_snapshot(
        self, run_id: str, snapshot: Any, *, every: int = SNAPSHOT_EVERY,
        force: bool = False,
    ) -> bool:
        """Persist one snapshot if it falls on the decimation boundary.

        Returns whether a row was written, so a caller can assert the sampling
        rate instead of assuming it.
        """
        tick = int(snapshot.tick)
        if not force and every > 1 and (tick % every) != 0:
            return False

        robots = snapshot.robots or []
        moving = sum(1 for r in robots if r.get("status") == "MOVING")
        waiting = sum(
            1 for r in robots if r.get("status") in ("WAITING", "BLOCKED")
        )
        kpis = snapshot.kpis or {}
        self.conn.execute(
            """
            INSERT OR REPLACE INTO snapshots (
                run_id, tick, sim_time_s, tasks_complete, tasks_pending,
                robots_moving, robots_waiting, collisions, compute_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, tick, float(snapshot.sim_time),
                int(snapshot.tasks_complete), int(snapshot.tasks_pending),
                moving, waiting, int(kpis.get("collisions", 0)),
                float(kpis.get("compute_ms", 0.0)),
            ),
        )
        self._maybe_commit()
        return True

    def record_events(self, run_id: str, events: Iterable[dict]) -> int:
        """Persist discrete events. Never decimated - see schema.py."""
        rows = [
            (
                run_id, int(e.get("tick", 0)), float(e.get("sim_time", 0.0)),
                str(e.get("kind", "unknown")),
                json.dumps(
                    {k: v for k, v in e.items()
                     if k not in ("tick", "sim_time", "kind")},
                    sort_keys=True, default=str,
                ),
            )
            for e in events
        ]
        if not rows:
            return 0
        self.conn.executemany(
            """
            INSERT INTO events (run_id, tick, sim_time_s, kind, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._maybe_commit()
        return len(rows)

    def record_tasks(self, run_id: str, engine: Any) -> int:
        """Write one row per COMPLETED task at the end of a run."""
        rows = []
        for tid in engine.completed:
            t = engine.tasks[tid]
            rows.append((
                run_id, t.task_id, t.priority.value, float(t.payload_kg),
                t.assigned_robot, float(t.created_s), t.assigned_s,
                t.picked_s, t.completed_s, t.completion_time_s, t.wait_time_s,
                1 if (t.completed_s is not None
                      and t.completed_s > t.deadline_s) else 0,
            ))
        if not rows:
            return 0
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO task_records (
                run_id, task_id, priority, payload_kg, robot_id, created_s,
                assigned_s, picked_s, completed_s, completion_s, wait_s, late
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._maybe_commit(force=True)
        return len(rows)

    def record_violations(self, run_id: str, violations: Iterable[Any]) -> int:
        rows = [
            (run_id, v.tick, float(v.sim_time), v.robot_a, v.robot_b,
             float(v.distance_m))
            for v in violations
        ]
        if not rows:
            return 0
        self.conn.executemany(
            """
            INSERT INTO violations (run_id, tick, sim_time_s, robot_a,
                                    robot_b, distance_m)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._maybe_commit(force=True)
        return len(rows)

    # ------------------------------------------------------------------
    # reads for the analytics panel
    # ------------------------------------------------------------------
    def series(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM snapshots WHERE run_id = ? ORDER BY tick",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def completion_times(self, run_id: str) -> list[float]:
        rows = self.conn.execute(
            """
            SELECT completion_s FROM task_records
            WHERE run_id = ? AND completion_s IS NOT NULL
            ORDER BY task_id
            """,
            (run_id,),
        ).fetchall()
        return [float(r["completion_s"]) for r in rows]

    def event_counts(self, run_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT kind, COUNT(*) AS n FROM events
            WHERE run_id = ? GROUP BY kind ORDER BY kind
            """,
            (run_id,),
        ).fetchall()
        return {r["kind"]: int(r["n"]) for r in rows}

    def violation_count(self, run_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM violations WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------
    # comparisons
    # ------------------------------------------------------------------
    def save_comparison(self, scenario: str, comparison: Any) -> str:
        """Persist a PairedComparison result and return its id."""
        ci = comparison.interval_pct()
        verdict = comparison.verdict()
        cid = f"cmp-{scenario}-{comparison.metric}-{uuid.uuid4().hex[:8]}"
        from app.db.stats import mean as _mean

        self.conn.execute(
            """
            INSERT INTO comparisons (
                comparison_id, created_utc, scenario, metric, seeds,
                baseline_mean, treatment_mean, improvement_pct,
                ci95_low_pct, ci95_high_pct, status, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid, _utc_now(), scenario, comparison.metric,
                len(comparison.seeds),
                _mean(comparison.baseline), _mean(comparison.treatment),
                ci.mean, ci.low, ci.high, verdict["status"],
                json.dumps(comparison.as_dict(), sort_keys=True),
            ),
        )
        self._maybe_commit(force=True)
        return cid

    def latest_comparison(
        self, *, scenario: Optional[str] = None, metric: Optional[str] = None
    ) -> Optional[dict]:
        sql = ["SELECT * FROM comparisons"]
        where, args = [], []
        if scenario:
            where.append("scenario = ?")
            args.append(scenario)
        if metric:
            where.append("metric = ?")
            args.append(metric)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY created_utc DESC LIMIT 1")
        row = self.conn.execute("\n".join(sql), args).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["detail"] = json.loads(out.pop("detail_json"))
        return out

# File contains AI-generated response based on internal company sources
