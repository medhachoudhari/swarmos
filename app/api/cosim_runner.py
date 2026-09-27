"""Co-simulation run manager (X-12): the counterfactual showpiece.

This is a SEPARATE manager from app.api.runner.RunManager, and that separation
is deliberate rather than accidental duplication.

RunManager owns the single authoritative SimEngine for the live fleet, which is
architectural law 1. A co-simulation owns TWO engines that are both hypothetical
- neither of them is "the fleet". Folding a second engine into RunManager would
have meant giving the authoritative engine a sibling and then teaching every
reader which of the two to trust, which is exactly the ambiguity law 1 exists to
prevent. So the co-simulation gets its own manager, its own loop, its own
subscriber set and its own socket, and the live map is never fed from it.

The cost of that choice is a second drift-corrected loop that looks similar to
the first. It is worth paying: the two loops have genuinely different stop
conditions (the live run stops when the scenario finishes, a co-simulation stops
at a fixed tick horizon so the two arms are always compared over equal time) and
a shared loop would have needed a mode flag threaded through every branch.

Honesty rules enforced here:
  - The horizon is fixed up front and reported in every frame. A comparison
    where one arm ran longer than the other is not a comparison.
  - A fault is injected into BOTH arms. Faulting only the baseline would be
    rigging the experiment, and cosim.inject() has no single-arm mode by design.
  - The final summary carries both trace hashes so the whole run is replayable.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from app.sim.clock import TICK_HZ, TICK_SECONDS
from app.sim.cosim import ARM_BASELINE, ARM_TREATMENT, CoSimulation
from app.sim.scenarios import DEFAULT_SCENARIO, get_scenario

# A co-simulation runs two engines per tick, so its per-tick cost is roughly
# double a live run. 3000 ticks is 300 s of sim time, which is longer than any
# demo, and past that the browser's delta history stops being readable.
MAX_TICKS = 3000

# 1800 ticks = 180 s of sim time. Anything shorter is a startup transient and
# must not be quoted as a throughput result; that was measured, not assumed.
DEFAULT_TICKS = 1800

# The measured parity fleet size. See the fleet-size curve in the session
# summaries: at fleet 8 the coordinated fleet completes 20 tasks against the
# baseline's 22, so this is the size at which the demo is honest about
# throughput and can put the weight on fault behaviour instead.
DEFAULT_FLEET = 8


@dataclass
class CoSimConfig:
    """Everything needed to reproduce a co-simulation exactly."""

    scenario: str = DEFAULT_SCENARIO
    seed: int = 11
    fleet_size: Optional[int] = DEFAULT_FLEET
    ticks: int = DEFAULT_TICKS
    speed: float = 1.0
    integrity: bool = False

    def normalised(self) -> "CoSimConfig":
        get_scenario(self.scenario)  # raises on an unknown name
        fleet = self.fleet_size
        if fleet is not None:
            fleet = max(2, min(50, int(fleet)))
        return CoSimConfig(
            scenario=self.scenario,
            seed=int(self.seed),
            fleet_size=fleet,
            ticks=max(1, min(MAX_TICKS, int(self.ticks))),
            speed=max(0.1, min(20.0, float(self.speed))),
            integrity=bool(self.integrity),
        )

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "seed": self.seed,
            "fleet_size": self.fleet_size,
            "ticks": self.ticks,
            "speed": self.speed,
            "integrity": self.integrity,
        }


class CoSimManager:
    """Owns the live CoSimulation, its loop and its subscriber set."""

    def __init__(self) -> None:
        self.cosim: Optional[CoSimulation] = None
        self.config: Optional[CoSimConfig] = None
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._last_frame: Optional[dict] = None
        self._summary: Optional[dict] = None
        self._overruns = 0
        self._max_tick_ms = 0.0

    # ---------------------------------------------------------- subscribers

    def subscribe(self) -> asyncio.Queue:
        """Bounded per-client queue: a slow browser drops frames, never stalls
        the loop. Same reasoning as RunManager.subscribe."""
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
                # Newest frame wins: a stale side-by-side is worse than a gap.
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass

    # --------------------------------------------------------------- state

    @property
    def has_run(self) -> bool:
        return self.cosim is not None

    def hello_payload(self) -> dict:
        if self.cosim is None:
            return {
                "type": "cosim_hello",
                "schema_version": "1.0",
                "running": False,
                "tick_hz": TICK_HZ,
                "arms": [ARM_TREATMENT, ARM_BASELINE],
                "warehouse": None,
                "config": None,
            }
        static = self.cosim.static_payload()
        return {
            "type": "cosim_hello",
            "schema_version": "1.0",
            "running": self.running,
            "tick_hz": static.get("tick_hz", TICK_HZ),
            "arms": [ARM_TREATMENT, ARM_BASELINE],
            "warehouse": static.get("warehouse"),
            "fleet": static.get("fleet"),
            "collision_distance_m": static.get("collision_distance_m"),
            "horizon_ticks": self.config.ticks if self.config else None,
            "config": self.config.as_dict() if self.config else None,
        }

    def last_frame(self) -> Optional[dict]:
        return self._last_frame

    def summary(self) -> Optional[dict]:
        """The banked summary of the last completed run, if there is one."""
        return self._summary

    def status(self) -> dict:
        return {
            "running": self.running,
            "has_run": self.has_run,
            "config": self.config.as_dict() if self.config else None,
            "tick": self.cosim.tick if self.cosim else None,
            "horizon_ticks": self.config.ticks if self.config else None,
            "in_lockstep": self.cosim.in_lockstep if self.cosim else None,
            "clients": len(self._subscribers),
            "overruns": self._overruns,
            "max_tick_ms": round(self._max_tick_ms, 3),
            # Present only once a run has finished. Absent means "not known
            # yet", which the UI must render as -- and not as zero.
            "summary": self._summary,
        }

    # ------------------------------------------------------------- control

    async def start(self, cfg: CoSimConfig) -> dict:
        async with self._lock:
            await self._stop_task()
            cfg = cfg.normalised()
            self.cosim = CoSimulation(
                cfg.scenario,
                seed=cfg.seed,
                fleet_size=cfg.fleet_size,
                integrity=cfg.integrity,
            )
            self.config = cfg
            self.running = True
            self._last_frame = None
            self._summary = None
            self._overruns = 0
            self._max_tick_ms = 0.0
            self._publish(self.hello_payload())
            self._task = asyncio.create_task(self._loop(), name="swarmos-cosim-loop")
            return {"ok": True, "config": cfg.as_dict(), "status": self.status()}

    async def stop(self) -> dict:
        async with self._lock:
            await self._stop_task()
            self.running = False
            if self.cosim is not None:
                # Bank the summary BEFORE dropping the replay frame, so a
                # stopped run can still be quoted and replayed.
                self._summary = self.cosim.summary()
            self._last_frame = None
            self._publish({"type": "cosim_reset", "schema_version": "1.0",
                           "reason": "Co-simulation stopped by the operator.",
                           "summary": self._summary})
            return {"ok": True, "status": self.status()}

    async def inject(self, fault: str) -> dict:
        if self.cosim is None:
            return {"ok": False,
                    "error": "No co-simulation in progress. Nothing to fault."}
        try:
            self.cosim.inject(fault)
        except Exception as exc:
            return {"ok": False,
                    "error": f"Could not inject '{fault}': {exc}"}
        # Said out loud because it is the whole point: both arms get the same
        # fault at the same tick, so any divergence afterwards is the policy.
        return {"ok": True, "fault": fault, "arms": [ARM_TREATMENT, ARM_BASELINE],
                "tick": self.cosim.tick}

    # ------------------------------------------------------------ the loop

    def _emit(self, frame: dict) -> None:
        self._last_frame = frame
        self._publish(frame)

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
        """Absolute-deadline loop, stopping at the fixed tick horizon.

        Drift correction and the no-catch-up rule are the same as the live
        loop, and for the same reasons; see app/api/runner.py. The difference
        is the stop condition: a co-simulation ends at its horizon so both
        arms are always measured over identical sim time.
        """
        assert self.cosim is not None and self.config is not None
        period = TICK_SECONDS / max(0.1, self.config.speed)
        horizon = self.config.ticks
        start = time.monotonic()
        base_tick = self.cosim.tick
        try:
            while self.running and self.cosim.tick < horizon:
                t0 = time.perf_counter()
                frame = self.cosim.step()
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self._max_tick_ms = max(self._max_tick_ms, elapsed_ms)
                if elapsed_ms > period * 1000.0:
                    self._overruns += 1
                self._emit(frame)

                n = self.cosim.tick - base_tick
                sleep_for = (start + n * period) - time.monotonic()
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                else:
                    # Behind schedule: yield to the sockets, do not burst.
                    await asyncio.sleep(0)

            if self.cosim.tick >= horizon:
                self.running = False
                self._summary = self.cosim.summary()
                self._publish({
                    "type": "cosim_done", "schema_version": "1.0",
                    "running": False, "tick": self.cosim.tick,
                    "horizon_ticks": horizon,
                    "summary": self._summary,
                })
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never fail silently
            self.running = False
            self._publish({
                "type": "error", "schema_version": "1.0",
                "cause": f"The co-simulation stopped: {type(exc).__name__}: {exc}",
                "action": "Press Compare to begin a fresh co-simulation.",
            })
            raise


# One co-simulation manager per process. Imported by app.api.server.
cosim_manager = CoSimManager()
