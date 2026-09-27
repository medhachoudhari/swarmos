"""SWARMOS M6 - the multi-seed A/B harness (X-13, X-03).

This is the machinery that turns the >=20% claim from an assertion into a
measurement. It runs both arms over a seed list, persists every run, and hands
the paired result to stats.py for the confidence interval.

Fairness rules, fixed here so no caller can bend them:

  Both arms get the SAME seed, the SAME scenario and the SAME tick count. The
  only difference between the arms is the policy object.

  Both arms are measured with the SAME code path - SimEngine.kpis() - so the
  comparison cannot be biased by one arm being instrumented more generously
  than the other.

  A seed on which EITHER arm completed no tasks is excluded from the paired
  statistics and reported explicitly in `excluded_seeds`. That is not
  cherry-picking: a percentage improvement over a baseline of zero is undefined,
  and silently dropping such seeds or treating them as an infinite win would
  both be dishonest. Naming them keeps the reader in a position to object.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from app.db import stats
from app.db.recorder import TraceRecorder, trace_path
from app.db.store import RunStore

# The published seed list. Fixed rather than random so any reader can reproduce
# the exact reported numbers, and ten-strong to satisfy MIN_SEEDS.
DEFAULT_SEEDS: tuple[int, ...] = (
    11, 13, 17, 23, 29, 31, 37, 41, 43, 47,
)

DEFAULT_TICKS = 1800          # 180 s of simulated time at 10 Hz

PolicyFactory = Callable[[], Any]


@dataclass
class ArmResult:
    """One arm of one seed."""

    label: str
    policy: str
    seed: int
    run_id: Optional[str]
    ticks: int
    kpis: dict
    trace_hash: str
    wall_s: float

    def metric(self, name: str) -> Optional[float]:
        value = self.kpis.get(name)
        return None if value is None else float(value)


@dataclass
class BenchmarkResult:
    """Everything a run of the harness produced."""

    scenario: str
    ticks: int
    seeds: tuple[int, ...]
    baseline: dict[int, ArmResult] = field(default_factory=dict)
    treatment: dict[int, ArmResult] = field(default_factory=dict)
    excluded_seeds: dict[int, str] = field(default_factory=dict)

    @property
    def usable_seeds(self) -> tuple[int, ...]:
        return tuple(s for s in self.seeds if s not in self.excluded_seeds)

    def compare(
        self, metric: str = "avg_completion_s", *, lower_is_better: bool = True,
    ) -> stats.PairedComparison:
        per_seed: dict[int, tuple[float, float]] = {}
        for seed in self.usable_seeds:
            b = self.baseline[seed].metric(metric)
            t = self.treatment[seed].metric(metric)
            if b is None or t is None:
                continue
            per_seed[seed] = (b, t)
        cmp_ = stats.paired(metric, per_seed, lower_is_better=lower_is_better)
        for seed, why in sorted(self.excluded_seeds.items()):
            cmp_.notes.append(f"seed {seed} excluded: {why}")
        return cmp_

    def safety_summary(self) -> dict:
        """Collision totals per arm. The zero-collision criterion, aggregated."""
        def total(arm: dict[int, ArmResult]) -> int:
            return sum(int(r.kpis.get("collisions", 0)) for r in arm.values())

        return {
            "baseline_collisions": total(self.baseline),
            "treatment_collisions": total(self.treatment),
            "baseline_near_misses": sum(
                int(r.kpis.get("near_misses", 0)) for r in self.baseline.values()
            ),
            "treatment_near_misses": sum(
                int(r.kpis.get("near_misses", 0)) for r in self.treatment.values()
            ),
        }

    def realtime_summary(self) -> dict:
        """Worst observed tick cost per arm, against the 100 ms budget (X-04)."""
        def worst(arm: dict[int, ArmResult]) -> Optional[float]:
            vals = [
                (r.kpis.get("compute") or {}).get("p95_ms")
                for r in arm.values()
            ]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None

        return {
            "budget_ms": 100.0,
            "baseline_worst_p95_ms": worst(self.baseline),
            "treatment_worst_p95_ms": worst(self.treatment),
        }

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "ticks": self.ticks,
            "seeds": list(self.seeds),
            "usable_seeds": list(self.usable_seeds),
            "excluded_seeds": dict(self.excluded_seeds),
            "safety": self.safety_summary(),
            "realtime": self.realtime_summary(),
            "completion_time": self.compare("avg_completion_s").as_dict(),
            "throughput": self.compare(
                "tasks_per_min", lower_is_better=False
            ).as_dict(),
        }

    def render(self) -> str:
        lines = [
            "=" * 68,
            f"SWARMOS benchmark - scenario {self.scenario}, {self.ticks} ticks",
            "=" * 68,
            "",
            self.compare("avg_completion_s").render(),
            "",
            self.compare("tasks_per_min", lower_is_better=False).render(),
            "",
        ]
        safety = self.safety_summary()
        lines.append(
            f"collisions  : baseline {safety['baseline_collisions']}, "
            f"swarmos {safety['treatment_collisions']} "
            f"(target 0 for both arms)"
        )
        rt = self.realtime_summary()
        lines.append(
            f"tick p95    : baseline {rt['baseline_worst_p95_ms']} ms, "
            f"swarmos {rt['treatment_worst_p95_ms']} ms "
            f"(budget {rt['budget_ms']} ms)"
        )
        if self.excluded_seeds:
            lines.append("")
            for seed, why in sorted(self.excluded_seeds.items()):
                lines.append(f"excluded seed {seed}: {why}")
        return "\n".join(lines)


def run_one(
    scenario: str,
    *,
    seed: int,
    ticks: int,
    label: str,
    policy_factory: Optional[PolicyFactory],
    store: Optional[RunStore] = None,
    record_trace: bool = False,
) -> ArmResult:
    """Run a single arm headless and persist it if a store was supplied."""
    from app.sim import SimEngine

    policy = policy_factory() if policy_factory is not None else None
    eng = SimEngine(scenario, seed=seed, policy=policy, label=label)

    # The scenario argument may be a name or a ScenarioSpec; the store records
    # a name. Reading it back off the engine resolves both forms to the same
    # string, so a spec built in code is recorded under the scenario it derives
    # from instead of being bound as an object.
    scenario_name = eng.scenario.name

    run_id: Optional[str] = None
    if store is not None:
        run_id = store.start_run(
            scenario=scenario_name, label=label, policy=eng.policy.name,
            seed=seed, fleet_size=eng.scenario.fleet_size,
        )


    recorder: Optional[TraceRecorder] = None
    if record_trace and run_id is not None:
        recorder = TraceRecorder(
            trace_path(run_id), run_id=run_id, static=eng.static_payload()
        )

    started = time.monotonic()
    snapshot = None
    seen_events = 0
    for _ in range(ticks):
        snapshot = eng.step()
        if recorder is not None:
            recorder.record(snapshot)
        if store is not None:
            store.record_snapshot(run_id, snapshot)
            if snapshot.events:
                store.record_events(run_id, snapshot.events)
                seen_events += len(snapshot.events)
    wall = time.monotonic() - started

    kpis = eng.kpis()
    if store is not None:
        store.record_tasks(run_id, eng)
        store.record_violations(run_id, eng.violations)
        store.finish_run(
            run_id, ticks=ticks, sim_time_s=eng.sim_time,
            trace_hash=eng.trace_hash, kpis=kpis,
        )
    if recorder is not None:
        recorder.close(kpis=kpis, trace_hash=eng.trace_hash)

    return ArmResult(
        label=label, policy=eng.policy.name, seed=seed, run_id=run_id,
        ticks=ticks, kpis=kpis, trace_hash=eng.trace_hash, wall_s=wall,
    )


def run_ab(
    scenario: str,
    *,
    baseline_factory: PolicyFactory,
    treatment_factory: PolicyFactory,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    ticks: int = DEFAULT_TICKS,
    store: Optional[RunStore] = None,
    record_trace: bool = False,
    progress: bool = False,
) -> BenchmarkResult:
    """Run both arms across `seeds` and return the paired result."""
    result = BenchmarkResult(
        scenario=scenario, ticks=ticks, seeds=tuple(sorted(seeds))
    )

    for seed in result.seeds:
        base = run_one(
            scenario, seed=seed, ticks=ticks, label="baseline",
            policy_factory=baseline_factory, store=store,
            record_trace=record_trace,
        )
        treat = run_one(
            scenario, seed=seed, ticks=ticks, label="swarmos",
            policy_factory=treatment_factory, store=store,
            record_trace=record_trace,
        )
        result.baseline[seed] = base
        result.treatment[seed] = treat

        if base.kpis.get("tasks_complete", 0) <= 0:
            result.excluded_seeds[seed] = (
                "baseline completed no tasks, so a percentage improvement is "
                "undefined"
            )
        elif treat.kpis.get("tasks_complete", 0) <= 0:
            result.excluded_seeds[seed] = (
                "treatment completed no tasks, which is a failure to "
                "investigate rather than a result to average"
            )

        if progress:
            print(
                f"seed {seed:>3}: baseline {base.kpis.get('tasks_complete')} tasks "
                f"@ {base.kpis.get('avg_completion_s')} s | "
                f"swarmos {treat.kpis.get('tasks_complete')} tasks "
                f"@ {treat.kpis.get('avg_completion_s')} s "
                f"({base.wall_s + treat.wall_s:.1f} s wall)",
                flush=True,
            )

    return result


def message_scaling(
    scenario: str,
    *,
    policy_factory: PolicyFactory,
    sizes: Sequence[int] = (10, 25, 50, 100),
    ticks: int = 600,
    seed: int = 11,
) -> dict:
    """Messages per robot per tick as the fleet grows. This is X-03.

    A flat series is the evidence that coordination is local and message
    complexity is O(k) rather than O(N^2). A rising series would mean the design
    does not actually scale, and this function is written to be capable of
    showing that.
    """
    from app.sim import SimEngine
    from app.sim.scenarios import get_scenario, scalability_variants

    base = get_scenario(scenario)
    rows = []
    for spec in scalability_variants(base, sizes=tuple(sizes)):
        eng = SimEngine(spec, seed=seed, policy=policy_factory())
        eng.run(ticks)
        stats_ = eng.policy.stats() if hasattr(eng.policy, "stats") else {}
        messages = int(stats_.get("messages", 0))
        denom = max(1, ticks * spec.fleet_size)
        rows.append({
            "fleet_size": spec.fleet_size,
            "ticks": ticks,
            "messages_total": messages,
            "msgs_per_robot_tick": round(messages / denom, 6),
            "tasks_complete": eng.kpis()["tasks_complete"],
            "collisions": eng.kpis()["collisions"],
            "compute_p95_ms": eng.clock.compute_stats().get("p95_ms"),
        })

    per = [r["msgs_per_robot_tick"] for r in rows]
    spread = (max(per) - min(per)) if per else 0.0
    return {
        "scenario": scenario,
        "rows": rows,
        "flat": spread <= 0.5,
        "spread": round(spread, 6),
        "note": (
            "msgs_per_robot_tick is expected to stay flat as fleet_size grows, "
            "because the bounded radio (R_comm = 15 m) caps how many peers any "
            "robot can talk to regardless of fleet size"
        ),
    }

# File contains AI-generated response based on internal company sources
