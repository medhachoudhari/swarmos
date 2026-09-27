"""
M5 SimClock - the fixed-rate deterministic clock.

Frozen convention: 10 Hz, 100 ms per tick. Simulation time is derived from the
tick counter alone and never from wall time, so a replay of the same seed
produces exactly the same trace. Wall time is measured only to report compute
headroom (X-04) and never to advance state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

TICK_HZ = 10
TICK_SECONDS = 1.0 / TICK_HZ
TICK_BUDGET_MS = 1000.0 / TICK_HZ


@dataclass
class SimClock:
    """Deterministic tick counter with a wall-clock compute probe.

    sim_time is a pure function of tick, so two runs with identical seeds and
    identical inputs cannot diverge through timing.
    """

    tick: int = 0
    epoch: float = 0.0
    _compute_ms: list[float] = field(default_factory=list, repr=False)
    _t0: float = field(default=0.0, repr=False)

    @property
    def sim_time(self) -> float:
        """Simulation seconds since start. Derived from tick only."""
        return self.tick * TICK_SECONDS

    @property
    def timestamp(self) -> float:
        """Unix-epoch-style timestamp for AMRState.timestamp."""
        return self.epoch + self.sim_time

    def begin(self) -> None:
        """Mark the start of a tick's compute window."""
        self._t0 = time.perf_counter()

    def end(self) -> float:
        """Close the compute window, record and return elapsed milliseconds."""
        dt_ms = (time.perf_counter() - self._t0) * 1000.0
        self._compute_ms.append(dt_ms)
        if len(self._compute_ms) > 2000:
            del self._compute_ms[:1000]
        return dt_ms

    def advance(self) -> int:
        self.tick += 1
        return self.tick

    # --- X-04 compute budget reporting -----------------------------------

    def compute_stats(self) -> dict:
        """Tick compute statistics against the 100 ms budget.

        Returns real measured values. Never synthesised.
        """
        s = sorted(self._compute_ms)
        n = len(s)
        if n == 0:
            return {
                "samples": 0, "budget_ms": TICK_BUDGET_MS,
                "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
                "max_ms": 0.0, "headroom_pct": 100.0,
            }

        def pct(p: float) -> float:
            idx = min(n - 1, max(0, int(round(p * (n - 1)))))
            return s[idx]

        p95 = pct(0.95)
        return {
            "samples": n,
            "budget_ms": TICK_BUDGET_MS,
            "p50_ms": round(pct(0.50), 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(pct(0.99), 3),
            "max_ms": round(s[-1], 3),
            "headroom_pct": round(
                max(0.0, (TICK_BUDGET_MS - p95) / TICK_BUDGET_MS * 100.0), 1),
        }

    def reset(self) -> None:
        self.tick = 0
        self._compute_ms.clear()

# File contains AI-generated response based on internal company sources
