"""Run manager: owns the one authoritative SimEngine and the 10 Hz loop.

Architectural law 1 says the simulation is the SINGLE source of robot state, so
exactly one engine exists per process and every reader goes through this object.
Nothing else is allowed to construct a SimEngine for the live run.

Two things here are worth stating plainly because they are easy to get wrong:

1. The loop is DRIFT-CORRECTED. It sleeps until an absolute next-tick deadline
   computed from the run start, not for a fixed 100 ms after each tick. A fixed
   sleep accumulates the compute time of every tick and the clock slowly falls
   behind; over a five-minute demo that is a visible drift.

2. When a tick overruns its budget the loop does NOT try to catch up by running
   several ticks back-to-back. It reports the overrun and moves to the next
   deadline. Catching up would compress sim time on screen, which would look
   like robots teleporting, and would hide the very thing the compute-budget
   chart exists to show.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.coordination.swarm_policy import SwarmPolicy
from app.sim.clock import TICK_HZ, TICK_SECONDS
from app.sim.engine import SimEngine
from app.sim.policy import StopAndWaitPolicy
from app.sim.scenarios import DEFAULT_SCENARIO, FaultKind, get_scenario

# Baseline STUCK_TICKS=8 is the TUNED value measured in the fairness sweep. The
# baseline must be offered at its best setting, not at a handicapped default --
# a comparison against a crippled reference proves nothing.
BASELINE_STUCK_TICKS = 8

POLICIES = ("swarmos", "baseline")


def _make_policy(name: str, seed: int, integrity: bool = False):
    if name == "baseline":
        tuned = type(
            "TunedStopAndWait",
            (StopAndWaitPolicy,),
            {"STUCK_TICKS": BASELINE_STUCK_TICKS},
        )
        # The baseline has no integrity layer by design: being defenceless
        # against a lying robot is part of what the comparison measures.
        return tuned()
    return SwarmPolicy(integrity=integrity)


@dataclass
class RunConfig:
    """Everything needed to reproduce a run exactly."""

    scenario: str = DEFAULT_SCENARIO
    seed: int = 11
    fleet_size: Optional[int] = None
    policy: str = "swarmos"
    speed: float = 1.0
    integrity: bool = False

    def normalised(self) -> "RunConfig":
        spec = get_scenario(self.scenario)  # raises on an unknown name
        policy = self.policy if self.policy in POLICIES else "swarmos"
        fleet = self.fleet_size
        if fleet is not None:
            fleet = max(1, min(50, int(fleet)))
        return RunConfig(
            scenario=spec.name if hasattr(spec, "name") else self.scenario,
            seed=int(self.seed),
            fleet_size=fleet,
            policy=policy,
            speed=max(0.1, min(10.0, float(self.speed))),
            integrity=bool(self.integrity),
        )

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "fleet_size": self.fleet_size,
            "policy": self.policy,
            "speed": self.speed,
            "integrity": self.integrity,
        }


@dataclass
class RunStats:
    ticks_emitted: int = 0
    overruns: int = 0
    max_tick_ms: float = 0.0
    started_at: Optional[float] = None
    wall_elapsed_s: float = 0.0


class RunManager:
    """Single owner of the live engine, the loop task and the subscriber set."""

    def __init__(self) -> None:
        self.engine: Optional[SimEngine] = None
        self.config: Optional[RunConfig] = None
        self.running = False
        self.stats = RunStats()
        self._task: Optional[asyncio.Task] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._last_frame: Optional[dict] = None
        # Trace hashes keyed by (scenario, seed, policy, fleet, ticks). The
        # determinism receipt in the UI compares two entries from this.
        self._hashes: dict[str, str] = {}

    # ---------------------------------------------------------- subscribers

    def subscribe(self) -> asyncio.Queue:
        """A bounded queue per client.

        Bounded on purpose: a slow browser must drop frames, never apply back
        pressure to the control loop. A stalled websocket cannot be allowed to
        slow the simulation down.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _publish(self, msg: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # Drop the OLDEST frame and keep the newest: for a live map the
                # most recent position matters and a stale one does not.
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    # --------------------------------------------------------------- state

    @property
    def has_run(self) -> bool:
        return self.engine is not None

    def hello_payload(self) -> dict:
        if self.engine is None:
            return {
                "type": "hello",
                "schema_version": "1.0",
                "running": False,
                "tick_hz": TICK_HZ,
                "scenario": None,
                "seed": None,
                "warehouse": None,
                "config": None,
            }
        static = self.engine.static_payload()
        return {
            "type": "hello",
            "schema_version": "1.0",
            "running": self.running,
            "tick_hz": static.get("tick_hz", TICK_HZ),
            "scenario": self.config.scenario if self.config else None,
            "seed": static.get("seed"),
            "warehouse": static.get("warehouse"),
            "fleet": static.get("fleet"),
            "collision_distance_m": static.get("collision_distance_m"),
            "config": self.config.as_dict() if self.config else None,
        }

    def frame_payload(self, snapshot) -> dict:
        d = snapshot.as_dict()
        d["type"] = "frame"
        d["schema_version"] = "1.0"
        d["running"] = self.running
        return d

    def last_frame(self) -> Optional[dict]:
        return self._last_frame

    def status(self) -> dict:
        return {
            "running": self.running,
            "has_run": self.has_run,
            "config": self.config.as_dict() if self.config else None,
            "tick": self.engine.tick if self.engine else None,
            "sim_time_s": round(self.engine.sim_time, 2) if self.engine else None,
            "trace_hash": self.engine.trace_hash if self.engine else None,
            "clients": len(self._subscribers),
            "stats": {
                "ticks_emitted": self.stats.ticks_emitted,
                "overruns": self.stats.overruns,
                "max_tick_ms": round(self.stats.max_tick_ms, 3),
                "wall_elapsed_s": round(self.stats.wall_elapsed_s, 2),
            },
        }

    # ------------------------------------------------------------- control

    async def start(self, cfg: RunConfig) -> dict:
        async with self._lock:
            await self._stop_task()
            cfg = cfg.normalised()
            scenario = get_scenario(cfg.scenario)
            if cfg.fleet_size is not None and cfg.fleet_size != scenario.fleet_size:
                scenario = type(scenario)(
                    **{**scenario.__dict__, "fleet_size": cfg.fleet_size}
                )
            self.engine = SimEngine(
                scenario,
                seed=cfg.seed,
                policy=_make_policy(cfg.policy, cfg.seed,
                                    integrity=cfg.integrity),
                label=cfg.policy,
            )
            self.config = cfg
            self.stats = RunStats(started_at=time.monotonic())
            self.running = True
            self._last_frame = None
            self._publish(self.hello_payload())
            self._task = asyncio.create_task(self._loop(), name="swarmos-tick-loop")
            return {"ok": True, "config": cfg.as_dict(), "status": self.status()}

    async def pause(self) -> dict:
        if self.engine is None:
            return {"ok": False, "error": "No run to pause. Start a scenario first."}
        self.running = False
        self._publish({"type": "frame", "schema_version": "1.0", "running": False,
                       "tick": self.engine.tick, "sim_time": round(self.engine.sim_time, 2)})
        return {"ok": True, "status": self.status()}

    async def resume(self) -> dict:
        if self.engine is None:
            return {"ok": False, "error": "No run to resume. Start a scenario first."}
        if self.running:
            return {"ok": True, "status": self.status()}
        self.running = True
        # Re-base the deadline so the loop does not try to make up the time
        # spent paused by firing a burst of ticks.
        self.stats.started_at = time.monotonic()
        self._base_tick = self.engine.tick
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="swarmos-tick-loop")
        return {"ok": True, "status": self.status()}

    async def step(self, n: int = 1) -> dict:
        """Advance exactly n ticks while paused. The frame-accurate demo tool."""
        if self.engine is None:
            return {"ok": False, "error": "No run to step. Start a scenario first."}
        if self.running:
            # A Step click on a live run is unambiguous: the operator wants the
            # world frozen and then advanced by hand. Refusing and asking them
            # to press Pause first is a needless second click, and during a
            # five-minute demo a needless second click is a lost second.
            self.running = False
            await self._stop_task()
        n = max(1, min(100, int(n)))
        for _ in range(n):
            if self.engine.finished:
                break
            snapshot = self.engine.step()
            self._emit(snapshot)
        return {"ok": True, "ticks": n, "status": self.status()}

    async def stop(self) -> dict:
        async with self._lock:
            await self._stop_task()
            if self.engine is not None:
                self._remember_hash()
            self.running = False
            # Drop the replay frame. It is kept during a run so a browser that
            # connects mid-run sees the world immediately, but once the run is
            # over it describes a world that no longer exists - replaying it to
            # the next client would paint a dead fleet as if it were live. The
            # engine itself is kept so the trace hash stays queryable.
            self._last_frame = None
            self._publish({"type": "reset", "schema_version": "1.0",
                           "reason": "Run stopped by the operator."})
            return {"ok": True, "status": self.status()}

    async def inject(self, fault: str, **params: Any) -> dict:
        if self.engine is None:
            return {"ok": False, "error": "No run in progress. Nothing to fault."}
        kind = _FAULT_ALIASES.get(fault, fault)
        try:
            kind = FaultKind(kind)
        except ValueError:
            return {"ok": False,
                    "error": f"Unknown fault '{fault}'. Known: {[k.value for k in FaultKind]}"}
        clean = {k: v for k, v in params.items() if v is not None}
        try:
            detail = self.engine.inject(kind, **clean)
        except TypeError as exc:
            return {"ok": False, "error": f"Fault {kind.value} rejected the parameters: {exc}"}
        return {"ok": True, "fault": kind.value, "detail": detail}

    # ------------------------------------------------------------ the loop

    def _emit(self, snapshot) -> None:
        frame = self.frame_payload(snapshot)
        self._last_frame = frame
        self.stats.ticks_emitted += 1
        self._publish(frame)

    def _remember_hash(self) -> None:
        if self.engine is None or self.config is None:
            return
        key = (f"{self.config.scenario}:{self.config.seed}:{self.config.policy}:"
               f"{self.config.fleet_size}:{self.engine.tick}")
        self._hashes[key] = self.engine.trace_hash

    def trace_hash(self) -> dict:
        if self.engine is None:
            return {"ok": False, "error": "No run recorded. Start a scenario first."}
        self._remember_hash()
        return {
            "ok": True,
            "hash": self.engine.trace_hash,
            "tick": self.engine.tick,
            "config": self.config.as_dict() if self.config else None,
            "known": self._hashes,
        }

    async def _stop_task(self) -> None:
        self.running = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        """Absolute-deadline 10 Hz loop. See the module docstring."""
        assert self.engine is not None
        period = TICK_SECONDS / max(0.1, self.config.speed if self.config else 1.0)
        start = time.monotonic()
        base_tick = self.engine.tick
        try:
            while self.running and not self.engine.finished:
                t0 = time.perf_counter()
                snapshot = self.engine.step()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.stats.max_tick_ms = max(self.stats.max_tick_ms, elapsed_ms)
                if elapsed_ms > period * 1000.0:
                    self.stats.overruns += 1
                self._emit(snapshot)
                self.stats.wall_elapsed_s = time.monotonic() - start

                # Absolute next deadline: no accumulated drift.
                n = self.engine.tick - base_tick
                deadline = start + n * period
                sleep_for = deadline - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    # Behind schedule. Yield so the event loop can service the
                    # websockets, then continue -- do NOT burst to catch up.
                    await asyncio.sleep(0)
            if self.engine.finished:
                self.running = False
                self._remember_hash()
                self._publish({"type": "frame", "schema_version": "1.0",
                               "running": False, "tick": self.engine.tick,
                               "sim_time": round(self.engine.sim_time, 2)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a loop crash must be visible, never silent
            self.running = False
            self._publish({
                "type": "error", "schema_version": "1.0",
                "cause": f"The simulation loop stopped: {type(exc).__name__}: {exc}",
                "action": "Press Start to begin a fresh run.",
            })
            raise


# The UI speaks in plain operator language; the engine speaks FaultKind. Map at
# the boundary so neither has to know about the other's vocabulary.
_FAULT_ALIASES = {
    "robot_failure": "ROBOT_FAILURE",
    "comm_blackout": "COMM_BLACKOUT",
    "link_impair": "LINK_IMPAIR",
    "blocked_aisle": "BLOCK_AISLE",
    "clear_blockage": "CLEAR_BLOCKAGE",
    "rogue_agent": "ROGUE_ROBOT",
    "battery_drain": "BATTERY_DRAIN",
    "zone_partition": "ZONE_PARTITION",
    "task_burst": "TASK_BURST",
    "kill_ml": "KILL_ML",
}

# One manager per process. Imported by app.api.server.
manager = RunManager()
