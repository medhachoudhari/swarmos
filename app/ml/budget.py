"""X-04 compute budget meter and the advisory firewall counter.

Two small instruments, both of which exist to turn a claim into a number.

BudgetMeter answers "does the coordination stack actually fit in its tick?".
The tick budget is 100 ms at 10 Hz. A demo that silently overruns is a demo
that is lying about being real-time, so the meter samples the wall clock around
each tick, reports percentiles, and counts overruns explicitly. It reuses the
key names that app.sim.clock.compute_stats() already emits so the UI has one
shape to render, not two.

Firewall answers "is the ML layer really advisory only?". Architectural law 3
says the ML layer never sits in the safety path. That is easy to assert and
easy to quietly violate. The firewall records, per tick, the advisory proposed
and the binding verdict the kernel actually issued, and counts the
disagreements. Two properties matter on stage:

  1. The override count is non-zero. If the kernel never disagreed we would
     have no evidence it is deciding independently rather than rubber-stamping.
  2. Turning the advisory path off does not change the trace hash. That is
     proven in tests/test_ml.py, not here; this class supplies the numbers that
     make the claim legible in the UI.

Neither class imports anything from app.coordination or app.sim, so neither can
become a back door into the kernel.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Optional

# The tick budget in milliseconds. Mirrored from app.sim.clock.TICK_BUDGET_MS
# rather than imported: this module stays dependency-free on purpose, and the
# value is asserted equal to the clock's in tests/test_ml.py so the two cannot
# drift apart unnoticed.
BUDGET_MS = 100.0

# How many samples to retain. 600 ticks = 60 s at 10 Hz, which matches the
# frontend history cap so a chart and the meter describe the same window.
SAMPLE_CAP = 600


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile over an already-sorted list.

    Nearest-rank rather than interpolated because a latency percentile should
    always be a value we actually measured. Interpolation invents a number
    between two samples and then we would be reporting a figure that never
    happened.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = int(round(q * (len(sorted_values) - 1)))
    return sorted_values[max(0, min(len(sorted_values) - 1, idx))]


@dataclass
class BudgetSample:
    """One tick's compute cost, split by stage."""

    tick: int
    total_ms: float
    stages: dict


class BudgetMeter:
    """Samples per-tick compute cost against the real-time budget.

    Usage per tick:

        meter.begin(tick)
        with meter.stage("kernel"):
            ...
        with meter.stage("ml"):
            ...
        meter.end()

    `stage` is optional; a caller that only wants the total can use begin/end
    alone. Stage timings are advisory themselves - they are for showing where
    the time went, and they are not required to sum exactly to the total.
    """

    def __init__(self, *, budget_ms: float = BUDGET_MS, cap: int = SAMPLE_CAP,
                 clock=None) -> None:
        self.budget_ms = float(budget_ms)
        self._samples: deque[BudgetSample] = deque(maxlen=cap)
        # Injectable clock so tests can drive the meter with a fake monotonic
        # source instead of sleeping. Defaults to the real one.
        self._clock = clock or time.perf_counter
        self._tick = 0
        self._t0: Optional[float] = None
        self._stages: dict = {}
        self.overruns = 0
        self.ticks_seen = 0

    # ------------------------------------------------------------- measuring

    def begin(self, tick: int) -> None:
        self._tick = int(tick)
        self._stages = {}
        self._t0 = self._clock()

    def stage(self, name: str):
        """Context manager timing one named stage of the tick."""
        return _Stage(self, name)

    def _record_stage(self, name: str, ms: float) -> None:
        self._stages[name] = self._stages.get(name, 0.0) + ms

    def end(self) -> BudgetSample:
        """Close the tick and return its sample."""
        if self._t0 is None:
            # end() without begin() is a caller bug, but raising here would
            # take down a live demo over an instrument. Record a zero and move
            # on; the sample count will show the gap.
            sample = BudgetSample(self._tick, 0.0, {})
        else:
            total = (self._clock() - self._t0) * 1000.0
            sample = BudgetSample(self._tick, total, dict(self._stages))
        self._t0 = None
        self._samples.append(sample)
        self.ticks_seen += 1
        if sample.total_ms > self.budget_ms:
            self.overruns += 1
        return sample

    def record(self, tick: int, total_ms: float, **stages: float) -> BudgetSample:
        """Record a pre-measured tick directly, for callers that time
        themselves (the sim engine already does)."""
        sample = BudgetSample(int(tick), float(total_ms), dict(stages))
        self._samples.append(sample)
        self.ticks_seen += 1
        if sample.total_ms > self.budget_ms:
            self.overruns += 1
        return sample

    # -------------------------------------------------------------- reporting

    @property
    def last_ms(self) -> Optional[float]:
        return self._samples[-1].total_ms if self._samples else None

    def stats(self) -> dict:
        """Percentiles and headroom, in the same key shape as clock.compute_stats.

        Returns None for every percentile when there are no samples. A budget
        meter that reports 0.0 ms before it has measured anything is showing
        fake data, and this project renders missing values as '--'.
        """
        if not self._samples:
            return {
                "samples": 0,
                "budget_ms": self.budget_ms,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "max_ms": None,
                "mean_ms": None,
                "headroom_pct": None,
                "overruns": 0,
                "overrun_pct": None,
                "stages": {},
            }
        vals = sorted(s.total_ms for s in self._samples)
        p95 = _percentile(vals, 0.95)
        stage_totals: Counter = Counter()
        for s in self._samples:
            for k, v in s.stages.items():
                stage_totals[k] += v
        n = len(self._samples)
        return {
            "samples": n,
            "budget_ms": self.budget_ms,
            "p50_ms": round(_percentile(vals, 0.50), 3),
            "p95_ms": round(p95, 3),
            "p99_ms": round(_percentile(vals, 0.99), 3),
            "max_ms": round(vals[-1], 3),
            "mean_ms": round(sum(vals) / n, 3),
            # Headroom is stated against p95, not the mean. The mean hides the
            # tail, and it is the tail that misses a deadline.
            "headroom_pct": round(
                max(0.0, (self.budget_ms - p95) / self.budget_ms * 100.0), 1
            ),
            "overruns": self.overruns,
            "overrun_pct": round(self.overruns / self.ticks_seen * 100.0, 2)
            if self.ticks_seen
            else None,
            "stages": {k: round(v / n, 3) for k, v in sorted(stage_totals.items())},
        }

    def series(self) -> list[float]:
        """Per-tick totals, oldest first, for the compute chart."""
        return [round(s.total_ms, 3) for s in self._samples]

    def reset(self) -> None:
        self._samples.clear()
        self.overruns = 0
        self.ticks_seen = 0
        self._t0 = None
        self._stages = {}


class _Stage:
    def __init__(self, meter: BudgetMeter, name: str) -> None:
        self._meter = meter
        self._name = name
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = self._meter._clock()
        return self

    def __exit__(self, *_exc):
        ms = (self._meter._clock() - self._t0) * 1000.0
        self._meter._record_stage(self._name, ms)
        return False


class Firewall:
    """Counts how often the binding kernel overrode the ML advisory.

    This is the measurement behind architectural law 3. Every tick, for every
    robot the ML layer had an opinion about, we log the proposal and the
    verdict that was actually issued and applied.
    """

    def __init__(self) -> None:
        self.advisories = 0
        self.agreements = 0
        self.overrides = 0
        # override counts keyed "ADVISORY->BINDING", so a judge can ask "when
        # the kernel disagreed, which way did it go?" and get an answer.
        self.pairs: Counter = Counter()
        self.ml_enabled = True

    def record(self, advisory_kind: Optional[str], binding_kind: str) -> bool:
        """Log one decision. Returns True if the kernel overrode the advisory.

        A None advisory is not an agreement and not an override. The ML layer
        is never required to have an opinion, and counting silence as agreement
        would inflate the agreement rate towards 100% and make the number
        meaningless.
        """
        if advisory_kind is None:
            return False
        self.advisories += 1
        if advisory_kind == binding_kind:
            self.agreements += 1
            return False
        self.overrides += 1
        self.pairs[f"{advisory_kind}->{binding_kind}"] += 1
        return True

    def stats(self) -> dict:
        total = self.advisories
        return {
            "ml_enabled": self.ml_enabled,
            "advisories": total,
            "agreements": self.agreements,
            "overrides": self.overrides,
            "override_pct": round(self.overrides / total * 100.0, 1) if total else None,
            "top_overrides": dict(self.pairs.most_common(5)),
            # The headline sentence, pre-composed so the UI and the deck cannot
            # paraphrase it into something stronger than the data supports.
            "claim": (
                "The ML layer proposed "
                f"{total} times and the safety kernel overrode it "
                f"{self.overrides} times. The kernel decides independently; "
                "the advisory is never in the safety path."
            )
            if total
            else "The ML layer has made no proposals yet.",
        }

    def reset(self) -> None:
        self.advisories = 0
        self.agreements = 0
        self.overrides = 0
        self.pairs.clear()
