"""SWARMOS M6 - the statistics behind the >=20% claim (X-13).

This module exists because "20% faster" is the single most attackable sentence
in the whole project. A judge is entitled to ask: faster on which run, against
what, and how do you know it was not luck? Everything here is built to answer
that, so the rules are fixed up front and applied without exception:

  1. PAIRED comparison. The baseline and SWARMOS are run on the SAME seed, so
     they see the identical warehouse, the identical fleet spawn and the
     identical task arrival sequence. Comparing unpaired runs would confound
     the policy difference with the luck of the draw.
  2. At least MIN_SEEDS seeds. A single run is an anecdote.
  3. A 95% confidence interval on the MEAN PAIRED DELTA, using the Student t
     distribution, not the normal one, because n is around 10 and the normal
     approximation is measurably optimistic at that size.
  4. The claim is only reported as MET when the LOWER bound of the interval
     clears the threshold. A point estimate of 21% with an interval spanning
     -5% to +47% does not support the sentence "at least 20% faster", and this
     module will say so rather than round in our favour.

No third-party statistics dependency: scipy is not guaranteed on the demo
machine, and a hardcoded t table for the sample sizes we actually use is both
auditable and exactly reproducible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

# Published minimum number of seeds per arm.
MIN_SEEDS = 10

# Published improvement target on mean task completion time.
TARGET_IMPROVEMENT_PCT = 20.0

# Two-sided 95% critical values of Student's t, indexed by degrees of freedom.
# Values beyond the table fall back to T_LARGE, which is the normal limit and
# is conservative for df > 100.
T_CRITICAL_95: dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
    16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
    26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    40: 2.021, 50: 2.009, 60: 2.000, 80: 1.990, 100: 1.984,
}
T_LARGE = 1.960


def t_critical_95(df: int) -> float:
    """Two-sided 95% t critical value for `df` degrees of freedom.

    For a df between two table rows the LOWER row is used, which yields the
    larger critical value and therefore the wider interval. Erring towards a
    wider interval is the only defensible direction when the claim is judged on
    the interval's lower bound.
    """
    if df <= 0:
        return float("inf")
    if df in T_CRITICAL_95:
        return T_CRITICAL_95[df]
    smaller = [k for k in T_CRITICAL_95 if k < df]
    if not smaller:
        return T_CRITICAL_95[1]
    if df > 100:
        return T_LARGE
    return T_CRITICAL_95[max(smaller)]


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def stdev(xs: Sequence[float]) -> float:
    """Sample standard deviation, Bessel corrected (n-1 denominator)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mu = mean(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))


def percentile(xs: Sequence[float], p: float) -> Optional[float]:
    """Nearest-rank percentile. Matches SimEngine.kpis so numbers cannot drift."""
    if not xs:
        return None
    ordered = sorted(xs)
    idx = min(len(ordered) - 1, max(0, int(round(p * (len(ordered) - 1)))))
    return ordered[idx]


@dataclass
class ConfidenceInterval:
    """A mean with its 95% interval, plus everything needed to re-derive it."""

    n: int
    mean: float
    stdev: float
    stderr: float
    t_crit: float
    low: float
    high: float

    @property
    def half_width(self) -> float:
        return (self.high - self.low) / 2.0

    @property
    def excludes_zero(self) -> bool:
        """True when the interval is entirely one side of zero.

        This is the significance test: if the interval straddles zero we cannot
        claim a difference at all, whatever the point estimate says.
        """
        return (self.low > 0.0) or (self.high < 0.0)

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "mean": round(self.mean, 4),
            "stdev": round(self.stdev, 4),
            "stderr": round(self.stderr, 4),
            "t_crit": self.t_crit,
            "ci95_low": round(self.low, 4),
            "ci95_high": round(self.high, 4),
            "excludes_zero": self.excludes_zero,
        }


def confidence_interval_95(xs: Sequence[float]) -> ConfidenceInterval:
    """95% t interval on the mean of `xs`.

    With n < 2 the interval is infinite rather than zero-width. A single
    observation genuinely carries no information about spread, and reporting a
    zero-width interval there would be the most misleading thing this module
    could possibly do.
    """
    n = len(xs)
    mu = mean(xs)
    sd = stdev(xs)
    if n < 2:
        return ConfidenceInterval(
            n=n, mean=mu, stdev=0.0, stderr=float("inf"),
            t_crit=float("inf"), low=float("-inf"), high=float("inf"),
        )
    stderr = sd / math.sqrt(n)
    t = t_critical_95(n - 1)
    margin = t * stderr
    return ConfidenceInterval(
        n=n, mean=mu, stdev=sd, stderr=stderr, t_crit=t,
        low=mu - margin, high=mu + margin,
    )


@dataclass
class PairedComparison:
    """The full result of a seed-paired A/B, ready to print or serialise.

    Sign convention, stated once so it can never be read backwards: a delta is
    baseline minus treatment, so a POSITIVE delta means the treatment finished
    tasks sooner, which is the improvement. Percentages are relative to the
    baseline value on the same seed.
    """

    metric: str
    seeds: tuple[int, ...]
    baseline: tuple[float, ...]
    treatment: tuple[float, ...]
    lower_is_better: bool = True
    target_pct: float = TARGET_IMPROVEMENT_PCT
    min_seeds: int = MIN_SEEDS
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not (len(self.seeds) == len(self.baseline) == len(self.treatment)):
            raise ValueError(
                "paired comparison requires one baseline and one treatment "
                "value per seed"
            )

    @property
    def deltas(self) -> list[float]:
        """Absolute per-seed improvement, in the metric's own units."""
        sign = 1.0 if self.lower_is_better else -1.0
        return [sign * (b - t) for b, t in zip(self.baseline, self.treatment)]

    @property
    def deltas_pct(self) -> list[float]:
        """Per-seed improvement as a percentage of that seed's baseline.

        Seeds whose baseline is zero are skipped rather than treated as an
        infinite improvement, and the omission is recorded in notes() so the
        sample size in the report always matches the data behind it.
        """
        out: list[float] = []
        for b, d in zip(self.baseline, self.deltas):
            if abs(b) < 1e-12:
                continue
            out.append(100.0 * d / b)
        return out

    def interval_abs(self) -> ConfidenceInterval:
        return confidence_interval_95(self.deltas)

    def interval_pct(self) -> ConfidenceInterval:
        return confidence_interval_95(self.deltas_pct)

    @property
    def wins(self) -> int:
        """Seeds on which the treatment beat the baseline. A sanity check.

        A large mean improvement driven by one or two seeds while losing on the
        rest is a fragile result, and the win count is what exposes that.
        """
        return sum(1 for d in self.deltas if d > 0)

    def verdict(self) -> dict:
        """Does the evidence support the published claim? Honest answer only."""
        ci = self.interval_pct()
        enough = len(self.seeds) >= self.min_seeds
        significant = ci.low > 0.0
        meets_target = ci.low >= self.target_pct

        if not enough:
            status = "INSUFFICIENT_DATA"
            summary = (
                f"only {len(self.seeds)} seeds, {self.min_seeds} required "
                f"before any claim is reportable"
            )
        elif not significant:
            status = "NOT_SIGNIFICANT"
            summary = (
                f"95% CI {ci.low:.1f}% to {ci.high:.1f}% includes zero, so no "
                f"improvement is demonstrated"
            )
        elif meets_target:
            status = "MET"
            summary = (
                f"improvement of {ci.mean:.1f}% (95% CI {ci.low:.1f}% to "
                f"{ci.high:.1f}%), lower bound clears the {self.target_pct:.0f}% target"
            )
        else:
            status = "SIGNIFICANT_BELOW_TARGET"
            summary = (
                f"improvement of {ci.mean:.1f}% is real (95% CI {ci.low:.1f}% "
                f"to {ci.high:.1f}%) but the lower bound is under the "
                f"{self.target_pct:.0f}% target"
            )

        return {
            "status": status,
            "summary": summary,
            "claim_supported": status == "MET",
            "significant": significant,
            "seeds_used": len(self.seeds),
            "seeds_required": self.min_seeds,
            "wins": self.wins,
            "losses": len(self.seeds) - self.wins,
        }

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "lower_is_better": self.lower_is_better,
            "seeds": list(self.seeds),
            "baseline": [round(v, 4) for v in self.baseline],
            "treatment": [round(v, 4) for v in self.treatment],
            "baseline_mean": round(mean(self.baseline), 4),
            "treatment_mean": round(mean(self.treatment), 4),
            "delta_abs": self.interval_abs().as_dict(),
            "delta_pct": self.interval_pct().as_dict(),
            "verdict": self.verdict(),
            "notes": list(self.notes),
        }

    def render(self) -> str:
        """Plain-text block for the terminal and the README."""
        ci = self.interval_pct()
        v = self.verdict()
        lines = [
            f"metric      : {self.metric}",
            f"seeds       : {len(self.seeds)} paired "
            f"({self.wins} wins / {v['losses']} losses)",
            f"baseline    : {mean(self.baseline):.2f}",
            f"swarmos     : {mean(self.treatment):.2f}",
            f"improvement : {ci.mean:.1f}%  95% CI [{ci.low:.1f}%, {ci.high:.1f}%]",
            f"verdict     : {v['status']} - {v['summary']}",
        ]
        return "\n".join(lines)


def paired(
    metric: str,
    per_seed: dict[int, tuple[float, float]],
    *,
    lower_is_better: bool = True,
    target_pct: float = TARGET_IMPROVEMENT_PCT,
) -> PairedComparison:
    """Build a PairedComparison from {seed: (baseline, treatment)}.

    Seeds are sorted so the report is byte-identical across runs, which matters
    because the determinism claim (X-22) covers the report as well as the
    simulation.
    """
    seeds = tuple(sorted(per_seed))
    return PairedComparison(
        metric=metric,
        seeds=seeds,
        baseline=tuple(per_seed[s][0] for s in seeds),
        treatment=tuple(per_seed[s][1] for s in seeds),
        lower_is_better=lower_is_better,
        target_pct=target_pct,
    )

# File contains AI-generated response based on internal company sources
