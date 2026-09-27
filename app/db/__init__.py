"""SWARMOS M6 - persistence, replay traces and the evidence harness.

Import order below is deliberate and load-bearing. benchmark.py contains
`from app.db import stats`, which re-enters this package while it is still
initialising, so `stats` must already be bound as an attribute of the package
by the time benchmark is imported. Listing stats first satisfies that; swapping
the two lines produces an AttributeError at import time.

What lives where:

  schema.py     the SQL contract, one place, idempotent
  store.py      the only code in the project allowed to touch SQLite
  recorder.py   newline-delimited JSON traces, crash-survivable, replayable
  stats.py      paired confidence intervals behind the >=20% claim
  benchmark.py  the multi-seed A/B harness that produces the claim
"""

from __future__ import annotations

from app.db import stats
from app.db.schema import SCHEMA_SQL, SCHEMA_VERSION
from app.db.stats import (
    MIN_SEEDS,
    TARGET_IMPROVEMENT_PCT,
    ConfidenceInterval,
    PairedComparison,
    confidence_interval_95,
    mean,
    paired,
    percentile,
    stdev,
    t_critical_95,
)
from app.db.store import (
    COMMIT_INTERVAL_S,
    DEFAULT_DB_PATH,
    SNAPSHOT_EVERY,
    RunStore,
)
from app.db.recorder import (
    DEFAULT_TRACE_DIR,
    TRACE_VERSION,
    TraceRecorder,
    TraceSummary,
    diff_traces,
    iter_trace,
    read_trace,
    replay,
    trace_path,
    verify_determinism,
)
from app.db.benchmark import (  # noqa: E402  (must follow stats - see docstring)
    DEFAULT_SEEDS,
    DEFAULT_TICKS,
    ArmResult,
    BenchmarkResult,
    message_scaling,
    run_ab,
    run_one,
)

__all__ = [
    # schema
    "SCHEMA_SQL", "SCHEMA_VERSION",
    # store
    "RunStore", "DEFAULT_DB_PATH", "SNAPSHOT_EVERY", "COMMIT_INTERVAL_S",
    # traces
    "TraceRecorder", "TraceSummary", "TRACE_VERSION", "DEFAULT_TRACE_DIR",
    "iter_trace", "read_trace", "replay", "diff_traces", "trace_path",
    "verify_determinism",
    # statistics
    "stats", "ConfidenceInterval", "PairedComparison",
    "confidence_interval_95", "paired", "mean", "stdev", "percentile",
    "t_critical_95", "MIN_SEEDS", "TARGET_IMPROVEMENT_PCT",
    # benchmark
    "ArmResult", "BenchmarkResult", "run_one", "run_ab", "message_scaling",
    "DEFAULT_SEEDS", "DEFAULT_TICKS",
]

# File contains AI-generated response based on internal company sources
