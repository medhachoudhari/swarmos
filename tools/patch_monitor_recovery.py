"""One-shot source patch: give the safety monitor a stuck-robot recovery.

Why this script exists rather than a hand edit: the change touches three widely
separated regions of app/coordination/swarm_policy.py and must be applied
exactly once, so it is written as an idempotent, self-verifying transform that
refuses to run twice.

WHAT IS BEING FIXED, because this is the fault the isolation harness cornered
after six failed tuning attempts.

Stubbing the negotiation out and letting the X-09 safety monitor decide alone
("monitor_only") scored -63.2% against StopAndWaitPolicy. It then stayed at
EXACTLY -63.2% across a peer-staleness fix and a swept-geometry fix. An
unchanged number across two real fixes is the diagnosis: the thing being changed
is not the thing that is wrong.

The monitor enforces the baseline's own floor with the baseline's own geometry
and the baseline's own ascending-id resolution, so it should have landed within
noise of the baseline. What it did NOT copy is the baseline's escape hatch.
StopAndWaitPolicy says so in its own docstring:

    "A robot held for STUCK_TICKS consecutive ticks is issued a REROUTE so a run
     cannot wedge permanently. That is the standard 'wait, then replan'
     recovery."

So the baseline is not pure stop-and-wait - it has a deadlock breaker. The
monitor had none. A veto returned WAIT unconditionally, forever, and because the
veto path never touched the yield streak, the ladder's own YIELD_PATIENCE
recovery could not fire either. Any pair that wedged stayed wedged for the rest
of the run. That is what the near-miss counter was really reporting: 9260 for
monitor_only against 3057 for the baseline is not congestion, it is paralysis.

The arbiter was therefore being measured against a baseline that had a recovery
mechanism the arbiter lacked. Equal terms means both get one, at the same
threshold, so that only the negotiation differs between the two policies.
"""

from __future__ import annotations

import pathlib
import sys

TARGET = pathlib.Path(__file__).resolve().parents[1] / "app" / "coordination" / "swarm_policy.py"

# -- 1. the constant --------------------------------------------------------

ANCHOR_CONST = """# blocking an aisle almost immediately.
STALE_TICKS = 3
"""

NEW_CONST = ANCHOR_CONST + '''
# Consecutive safety-monitor vetoes after which the held robot is made to
# REPLAN instead of simply being told to wait again.
#
# This constant is the cure for the largest single throughput defect in this
# file, and it was found by isolation rather than by reasoning - see
# tools/diag_isolate.py and tools/patch_monitor_recovery.py for the full trail.
#
# StopAndWaitPolicy is not pure stop-and-wait: it issues a REROUTE after
# STUCK_TICKS consecutive holds so that a run cannot wedge permanently. That is
# the classical "wait, then replan" recovery, and the baseline has it. The
# monitor did not. A veto returned WAIT unconditionally and forever, and since
# the veto path never touched the yield streak, the ladder's own YIELD_PATIENCE
# recovery could not fire either. Every pair that wedged stayed wedged for the
# rest of the run: 9260 near misses against the baseline's 3057, which is not
# congestion but paralysis.
#
# 30 ticks matches StopAndWaitPolicy.STUCK_TICKS exactly, for precisely the same
# reason HARD_STOP_M matches SAFE_SEPARATION_M. The comparison between the two
# policies is a THROUGHPUT comparison, so every mechanism they share must be
# identical and only the negotiation may differ. Giving SWARMOS a faster escape
# hatch than the baseline would win the benchmark by changing the benchmark.
MONITOR_STUCK_TICKS = 30
'''

# -- 2. the per-robot counter ----------------------------------------------

ANCHOR_INIT = """        self._seq: dict[str, int] = {}
"""

NEW_INIT = """        self._seq: dict[str, int] = {}
        # Consecutive safety-monitor vetoes per robot. Drives the monitor's
        # own deadlock recovery at MONITOR_STUCK_TICKS; see there for why a
        # veto that can never expire cost more throughput than every distance
        # threshold in this file put together.
        self._veto_streak: dict[str, int] = {}
"""

# -- 3. the veto branch ----------------------------------------------------

ANCHOR_VETO = """            self._counters.monitor_vetoes += 1
            if proposal.kind is not VerdictKind.PROCEED:
                self._counters.monitor_overrides += 1
            return Verdict(
                robot_id=rid, kind=VerdictKind.WAIT,
                reason=(
                    f"safety monitor veto: swept path comes within "
                    f"{gap:.2f} m of {peer_id}, floor {HARD_STOP_M:.2f} m"
                ),
                conflict_with=(peer_id,),
                utility_terms=proposal.utility_terms,
                winning_margin=proposal.winning_margin,
            )
        return proposal
"""

NEW_VETO = """            self._counters.monitor_vetoes += 1
            if proposal.kind is not VerdictKind.PROCEED:
                self._counters.monitor_overrides += 1

            # Deadlock recovery, and the reason it lives HERE rather than in the
            # ladder above. A vetoed robot never reaches the contest, so its
            # yield streak never grows and YIELD_PATIENCE can never fire for it.
            # Without a recovery of its own the monitor can hold a robot for the
            # entire run, which is exactly what it was doing. The baseline has
            # this same escape hatch at the same threshold; see
            # MONITOR_STUCK_TICKS.
            streak = self._veto_streak.get(rid, 0) + 1
            self._veto_streak[rid] = streak
            if streak >= MONITOR_STUCK_TICKS:
                self._veto_streak[rid] = 0
                self._counters.reroutes += 1
                return Verdict(
                    robot_id=rid, kind=VerdictKind.REROUTE,
                    reason=(
                        f"safety monitor held {streak} ticks behind "
                        f"{peer_id}, replanning"
                    ),
                    conflict_with=(peer_id,),
                    utility_terms=proposal.utility_terms,
                    winning_margin=proposal.winning_margin,
                )

            return Verdict(
                robot_id=rid, kind=VerdictKind.WAIT,
                reason=(
                    f"safety monitor veto: swept path comes within "
                    f"{gap:.2f} m of {peer_id}, floor {HARD_STOP_M:.2f} m"
                ),
                conflict_with=(peer_id,),
                utility_terms=proposal.utility_terms,
                winning_margin=proposal.winning_margin,
            )

        # Cleared the whole inbox without a veto, so this robot is not stuck and
        # the streak must not carry over into a future, unrelated encounter.
        self._veto_streak.pop(rid, None)
        return proposal
"""

# -- 4. expose the count in stats() ----------------------------------------

ANCHOR_STATS = """            "vetoes_per_tick": round(c.monitor_vetoes / ticks, 3),
"""

NEW_STATS = """            "vetoes_per_tick": round(c.monitor_vetoes / ticks, 3),
            "robots_vetoed_now": len(self._veto_streak),
"""

EDITS = (
    ("MONITOR_STUCK_TICKS constant", ANCHOR_CONST, NEW_CONST),
    ("per-robot veto counter", ANCHOR_INIT, NEW_INIT),
    ("monitor recovery branch", ANCHOR_VETO, NEW_VETO),
    ("stats surface", ANCHOR_STATS, NEW_STATS),
)


def main() -> int:
    src = TARGET.read_text()

    if "MONITOR_STUCK_TICKS" in src:
        print("already patched, nothing to do")
        return 0

    for label, anchor, replacement in EDITS:
        count = src.count(anchor)
        if count != 1:
            print(f"ABORT: anchor for {label} matched {count} times, expected 1")
            return 1
        src = src.replace(anchor, replacement, 1)
        print(f"applied: {label}")

    TARGET.write_text(src)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# File contains AI-generated response based on internal company sources
