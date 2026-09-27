#!/usr/bin/env python3
"""Make _account_safety count collision EVENTS rather than overlapping TICKS.

The defect, proven in SESSION_SUMMARY_20260921_0020_collision_metric_defect.md:
_account_safety ran every tick and appended a Violation whenever a pair was
closer than COLLISION_DISTANCE_M, with no memory of the previous tick. A pair
that overlaps and then freezes - which happens when a robot fails next to an
already-stopped peer, since observed_states() hides failed robots from the
arbiter and the onboard brake skips robots that are already stopped - was
re-reported once per tick forever. On seed 13 the first overlap appeared at tick
430 of 900 and the run reported exactly 470 "collisions". 900 - 430 = 470.

After this patch:
  violations      one record per pair per ENTRY into the overlap state
  overlap_ticks   total pair-ticks spent overlapping, kept separately because
                  dwell is genuinely interesting, just not the headline number
  kpis()["collisions"]    = len(violations), now an event count
  kpis()["overlap_ticks"] = the old behaviour, retained for diagnosis

A pair must separate beyond NEAR_MISS_DISTANCE_M before it can be counted again.
Using the near-miss distance rather than the collision distance as the re-arm
threshold gives hysteresis, so a pair hovering either side of 0.70 m cannot
ratchet the count up on float noise.

Idempotent: re-running reports that the patch is already present and exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "app" / "sim" / "engine.py"

SENTINEL = "_overlapping: set[tuple[str, str]]"

# --- 1. new state, declared next to the other safety counters ---------------
INIT_ANCHOR = """        self.violations: list[Violation] = []
        self.near_misses = 0
"""
INIT_NEW = """        self.violations: list[Violation] = []
        self.near_misses = 0
        # Pairs currently inside COLLISION_DISTANCE_M. A Violation is recorded
        # only when a pair ENTERS this set, so one frozen overlap is one
        # collision rather than one per tick for the rest of the run. See
        # SESSION_SUMMARY_20260921_0020_collision_metric_defect.md.
        self._overlapping: set[tuple[str, str]] = set()
        # Pair-ticks spent overlapping. This is what `collisions` used to
        # measure. Kept because how long a breach persists matters, but it is
        # a dwell metric and must never be reported as a collision count.
        self.overlap_ticks = 0
"""

# --- 2. the detector itself -------------------------------------------------
DETECT_OLD = """                    d = a.distance_to(b.x, b.y)
                    if d < COLLISION_DISTANCE_M:
                        self.violations.append(
                            Violation(self.clock.tick, self.sim_time,
                                      a.robot_id, b.robot_id, d)
                        )
                        self._emit("safety_violation", robot_a=a.robot_id,
                                   robot_b=b.robot_id, distance_m=round(d, 4))
                    elif d < NEAR_MISS_DISTANCE_M:
                        self.near_misses += 1
"""
DETECT_NEW = """                    d = a.distance_to(b.x, b.y)
                    if d < COLLISION_DISTANCE_M:
                        self.overlap_ticks += 1
                        # Edge-triggered. Only the tick on which the pair first
                        # closes inside the threshold is a collision; the ticks
                        # it then spends overlapping are dwell, counted above.
                        if pair not in self._overlapping:
                            self._overlapping.add(pair)
                            self.violations.append(
                                Violation(self.clock.tick, self.sim_time,
                                          a.robot_id, b.robot_id, d)
                            )
                            self._emit("safety_violation", robot_a=a.robot_id,
                                       robot_b=b.robot_id, distance_m=round(d, 4))
                    elif d < NEAR_MISS_DISTANCE_M:
                        self.near_misses += 1
                        still_close.add(pair)
                    else:
                        # Fully separated, so the pair may be counted again if
                        # it ever closes a second time. Re-arming at the
                        # near-miss distance rather than the collision distance
                        # gives hysteresis: a pair sitting exactly on the
                        # 0.70 m boundary cannot ratchet the count up on float
                        # noise alone.
                        pass
"""

# --- 3. re-arm bookkeeping at the end of the sweep --------------------------
SWEEP_TAIL_OLD = """                    elif d < NEAR_MISS_DISTANCE_M:
                        self.near_misses += 1
                        still_close.add(pair)
                    else:
"""

KPI_OLD = """            "collisions": len(self.violations),
"""
KPI_NEW = """            "collisions": len(self.violations),
            # Pair-ticks spent inside the collision threshold. Reported
            # alongside the event count so a single frozen overlap is visibly
            # distinguishable from many brief ones.
            "overlap_ticks": self.overlap_ticks,
"""


def main() -> int:
    text = TARGET.read_text()

    if SENTINEL in text:
        print("collision-event patch already applied - nothing to do")
        return 0

    for name, old in (("init", INIT_ANCHOR), ("detector", DETECT_OLD), ("kpi", KPI_OLD)):
        if old not in text:
            print(f"ERROR: {name} anchor not found, aborting", file=sys.stderr)
            return 1

    text = text.replace(INIT_ANCHOR, INIT_NEW, 1)
    text = text.replace(DETECT_OLD, DETECT_NEW, 1)
    text = text.replace(KPI_OLD, KPI_NEW, 1)

    # The detector needs a `still_close` set and, after the sweep, needs to drop
    # pairs that are no longer near each other so they can re-arm. Insert both
    # around the existing `seen` set, which brackets the pair loop.
    seen_old = "        seen: set[tuple[str, str]] = set()\n"
    seen_new = (
        "        seen: set[tuple[str, str]] = set()\n"
        "        # Pairs seen this tick that are overlapping or merely near.\n"
        "        # Anything in self._overlapping but absent from these has moved\n"
        "        # fully apart and is re-armed at the bottom of this method.\n"
        "        still_close: set[tuple[str, str]] = set()\n"
    )
    if seen_old not in text:
        print("ERROR: seen-set anchor not found, aborting", file=sys.stderr)
        return 1
    text = text.replace(seen_old, seen_new, 1)

    # Record overlapping pairs into still_close too, so they are not re-armed
    # while they are still overlapping.
    text = text.replace(
        "                        if pair not in self._overlapping:\n"
        "                            self._overlapping.add(pair)\n",
        "                        still_close.add(pair)\n"
        "                        if pair not in self._overlapping:\n"
        "                            self._overlapping.add(pair)\n",
        1,
    )

    # Re-arm at the end of the sweep, immediately before the near_misses
    # bookkeeping ends the method.
    tail_anchor = "                        self.near_misses += 1\n                        still_close.add(pair)\n"
    idx = text.index(tail_anchor) + len(tail_anchor)
    # Find the end of the method: the next dedented `def ` at 4-space indent.
    nxt = text.index("\n    def ", idx)
    rearm = (
        "\n        # Pairs that have separated beyond the near-miss ring are\n"
        "        # forgotten, so a genuinely new approach later in the run is\n"
        "        # counted as a new collision rather than being suppressed.\n"
        "        self._overlapping &= still_close\n"
    )
    text = text[:nxt] + rearm + text[nxt:]

    if text.count(SENTINEL) != 1:
        print("ERROR: sentinel not present exactly once, aborting", file=sys.stderr)
        return 1

    TARGET.write_text(text)
    print("collision-event patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# File contains AI-generated response based on internal company sources
