"""SWARMOS M6 - the trace recorder and replayer (X-22, X-27).

A trace is a newline-delimited JSON file: one header line describing the run,
then one line per tick. That format is chosen deliberately over a single JSON
document or a binary format:

  it is append-only, so a run that is killed with SIGKILL mid-write leaves a
  file that is still readable up to the last complete line. The X-27 crash
  requirement is not satisfied by a format that must be closed to be valid.

  it streams, so a replay never has to hold the whole run in memory.

  it is greppable and diffable with ordinary tools, which is what makes the
  determinism claim checkable by someone who does not trust our code: run twice,
  diff the traces, and any divergence shows up at the exact tick it began.

The replay contract is narrow on purpose. A trace records WHAT HAPPENED, and
replaying it reproduces those observations exactly. It is not a re-simulation:
re-running the engine from the same seed is what regenerates the physics, and
verify_determinism() below is the function that asserts the two agree.
"""

from __future__ import annotations

import gzip
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Iterator, Optional

TRACE_VERSION = 1
DEFAULT_TRACE_DIR = "data/traces"


def _open_write(path: str) -> io.TextIOBase:
    if path.endswith(".gz"):
        return gzip.open(path, "wt", encoding="utf-8")
    return open(path, "w", encoding="utf-8")


def _open_read(path: str) -> io.TextIOBase:
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


class TraceRecorder:
    """Writes a run to a newline-delimited JSON trace.

    flush_every exists because of a direct tension: flushing on every tick makes
    the crash guarantee tightest but puts a write syscall inside the 100 ms
    budget, while never flushing makes the tick free and the guarantee useless.
    Flushing once per simulated second bounds the worst-case loss to ten ticks,
    which is one second of recoverable history, at a cost of one syscall per
    hundred milliseconds of simulation rather than per tick.
    """

    def __init__(
        self,
        path: str,
        *,
        run_id: str,
        static: dict,
        flush_every: int = 10,
        full_robots: bool = False,
    ) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.path = path
        self.run_id = run_id
        self.flush_every = max(1, int(flush_every))
        # Full robot dicts make a trace visually replayable but roughly ten
        # times larger. Off by default: the determinism check only needs the
        # hash and the counters.
        self.full_robots = full_robots
        self.ticks_written = 0

        self._fh = _open_write(path)
        self._write({
            "type": "header",
            "trace_version": TRACE_VERSION,
            "run_id": run_id,
            "static": static,
        })
        self._fh.flush()

    def _write(self, obj: dict) -> None:
        # sort_keys so two traces of the same run are byte-identical, which is
        # what makes a plain diff a valid determinism check.
        self._fh.write(json.dumps(obj, sort_keys=True, default=str) + "\n")

    def record(self, snapshot: Any) -> None:
        row: dict[str, Any] = {
            "type": "tick",
            "tick": snapshot.tick,
            "sim_time": round(snapshot.sim_time, 3),
            "tasks_complete": snapshot.tasks_complete,
            "tasks_pending": snapshot.tasks_pending,
            "tasks_active": snapshot.tasks_active,
            "trace_hash": snapshot.trace_hash,
            "collisions": (snapshot.kpis or {}).get("collisions", 0),
        }
        if snapshot.events:
            row["events"] = snapshot.events
        if snapshot.verdicts:
            # Only non-PROCEED verdicts reach the snapshot, so this is already
            # the interesting subset.
            row["verdicts"] = snapshot.verdicts
        if self.full_robots:
            row["robots"] = snapshot.robots

        self._write(row)
        self.ticks_written += 1
        if self.ticks_written % self.flush_every == 0:
            self._fh.flush()

    def close(self, *, kpis: Optional[dict] = None,
              trace_hash: Optional[str] = None) -> str:
        """Write the footer and close. Returns the trace path.

        A trace with no footer is a crashed run, and read_trace() reports that
        rather than pretending the run ended cleanly - an honest partial record
        is worth far more during a demo than a file that silently looks whole.
        """
        try:
            self._write({
                "type": "footer",
                "ticks": self.ticks_written,
                "trace_hash": trace_hash,
                "kpis": kpis or {},
            })
            self._fh.flush()
        finally:
            self._fh.close()
        return self.path

    def __enter__(self) -> "TraceRecorder":
        return self

    def __exit__(self, *exc: Any) -> None:
        if not self._fh.closed:
            self._fh.close()


@dataclass
class TraceSummary:
    """What a trace file turned out to contain."""

    path: str
    run_id: str
    trace_version: int
    static: dict
    ticks: int
    final_hash: Optional[str]
    footer: Optional[dict]
    truncated: bool
    corrupt_lines: int

    @property
    def clean(self) -> bool:
        return self.footer is not None and self.corrupt_lines == 0

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "run_id": self.run_id,
            "trace_version": self.trace_version,
            "ticks": self.ticks,
            "final_hash": self.final_hash,
            "truncated": self.truncated,
            "corrupt_lines": self.corrupt_lines,
            "clean": self.clean,
            "scenario": (self.static.get("scenario") or {}).get("name"),
            "seed": self.static.get("seed"),
        }


def iter_trace(path: str) -> Iterator[dict]:
    """Yield every well-formed record in a trace, skipping damaged lines.

    A truncated final line is expected after a kill -9 and is skipped in
    silence here; read_trace() is the function that counts and reports it.
    """
    with _open_read(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def read_trace(path: str) -> TraceSummary:
    """Parse a trace and report exactly what state it was left in."""
    header: dict = {}
    footer: Optional[dict] = None
    ticks = 0
    final_hash: Optional[str] = None
    corrupt = 0

    with _open_read(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                corrupt += 1
                continue
            kind = rec.get("type")
            if kind == "header":
                header = rec
            elif kind == "tick":
                ticks += 1
                final_hash = rec.get("trace_hash") or final_hash
            elif kind == "footer":
                footer = rec

    return TraceSummary(
        path=path,
        run_id=header.get("run_id", "unknown"),
        trace_version=int(header.get("trace_version", 0)),
        static=header.get("static", {}) or {},
        ticks=ticks,
        final_hash=(footer or {}).get("trace_hash") or final_hash,
        footer=footer,
        truncated=footer is None,
        corrupt_lines=corrupt,
    )


def replay(path: str) -> Iterator[dict]:
    """Yield only the tick records, in order. The X-27 replay path."""
    for rec in iter_trace(path):
        if rec.get("type") == "tick":
            yield rec


def diff_traces(path_a: str, path_b: str) -> Optional[dict]:
    """First tick at which two traces disagree, or None if identical.

    This is the determinism check a sceptic can run without reading any of our
    code: two runs of the same scenario and seed must produce traces that agree
    at every tick, and if they do not, this reports the exact tick and the two
    hashes rather than a bare boolean.
    """
    for a, b in zip(replay(path_a), replay(path_b)):
        if a.get("tick") != b.get("tick"):
            return {
                "reason": "tick sequence diverged",
                "tick_a": a.get("tick"), "tick_b": b.get("tick"),
            }
        if a.get("trace_hash") != b.get("trace_hash"):
            return {
                "reason": "state hash diverged",
                "tick": a.get("tick"),
                "hash_a": a.get("trace_hash"),
                "hash_b": b.get("trace_hash"),
            }
    sa, sb = read_trace(path_a), read_trace(path_b)
    if sa.ticks != sb.ticks:
        return {
            "reason": "different tick counts",
            "ticks_a": sa.ticks, "ticks_b": sb.ticks,
        }
    return None


def verify_determinism(
    scenario: str, *, seed: int, ticks: int, policy_factory: Any = None
) -> dict:
    """Run the same configuration twice and prove the traces agree.

    Two engines are built and stepped independently rather than one engine being
    reset, because a reset could hide exactly the kind of leaked state this is
    meant to catch.
    """
    from app.sim import SimEngine

    hashes: list[str] = []
    per_tick: list[list[str]] = []
    for _ in range(2):
        policy = policy_factory() if policy_factory is not None else None
        eng = SimEngine(scenario, seed=seed, policy=policy)
        seq: list[str] = []
        for _ in range(ticks):
            snap = eng.step()
            seq.append(snap.trace_hash)
        hashes.append(eng.trace_hash)
        per_tick.append(seq)

    first_divergence: Optional[int] = None
    for i, (x, y) in enumerate(zip(*per_tick)):
        if x != y:
            first_divergence = i
            break

    return {
        "scenario": scenario,
        "seed": seed,
        "ticks": ticks,
        "hash_a": hashes[0],
        "hash_b": hashes[1],
        "deterministic": hashes[0] == hashes[1] and first_divergence is None,
        "first_divergent_tick": first_divergence,
    }


def trace_path(run_id: str, *, directory: str = DEFAULT_TRACE_DIR,
               compress: bool = False) -> str:
    suffix = ".ndjson.gz" if compress else ".ndjson"
    return os.path.join(directory, f"{run_id}{suffix}")

# File contains AI-generated response based on internal company sources
