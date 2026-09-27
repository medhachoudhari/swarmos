"""X-01 step 3: the isolation detector, the tightened envelope and the report.

Three edits, in the order the data flows through one tick:

  1. arbitrate() calls _update_sovereign() immediately after _drain_round(), so
     every robot's inbox is already settled for this tick when the question "did
     I hear anybody?" is asked. Asking earlier would read last tick's view and
     delay entry by one tick for no reason.
  2. _monitor() widens its floor and caps its speed for a sovereign robot. The
     floor is a LOCAL variable, not a changed constant, so the fleet-wide safety
     rule that the baseline comparison depends on is untouched.
  3. stats() and explain() report it, because an operator who cannot see that a
     robot is running blind has been told a comfortable lie.
"""
import ast
import pathlib

P = pathlib.Path("app/coordination/swarm_policy.py")
text = P.read_text()


def sub(t, old, new, label):
    assert t.count(old) == 1, f"{label}: expected 1 match, got {t.count(old)}"
    return t.replace(old, new)


# --- 1. detector call + method --------------------------------------------
text = sub(
    text,
    """        self._broadcast_round(tick, sim_time, states)
        self._drain_round(tick, sim_time, ids)
""",
    """        self._broadcast_round(tick, sim_time, states)
        self._drain_round(tick, sim_time, ids)
        # X-01. Asked here, after the inboxes are settled and before any robot is
        # judged, so a robot that has just gone deaf is already under the
        # tightened envelope on the very tick its isolation is confirmed.
        self._update_sovereign(states, ids)
""",
    "detector call",
)

text = sub(
    text,
    """    def stats(self) -> dict:""",
    '''    def _update_sovereign(
        self, states: dict[str, AMRState], ids: list[str]
    ) -> None:
        """Maintain the sovereign set from each robot's own inbox (X-01).

        Entry needs SOVEREIGN_CONFIRM_TICKS consecutive ticks with not one fresh
        peer. Exit is immediate on the first peer heard, and needs no handshake:
        the sovereign envelope is strictly tighter than the normal one, so a
        robot relaxing back to the normal floor cannot invalidate a plan a peer
        made while it was isolated.

        A FAILED robot is dropped from the set silently and is NOT counted as a
        rejoin. It did not rejoin anything - it died - and inflating the rejoin
        count with corpses would make the recovery claim unfalsifiable.
        """
        for rid in ids:
            me = states.get(rid)
            if me is None or me.status is RobotStatus.FAILED:
                self._silence_streak.pop(rid, None)
                self._sovereign.discard(rid)
                continue

            fresh = self._fresh(self._views.setdefault(rid, {}))
            peers = sum(1 for pid in fresh if pid != rid)
            if peers > 0:
                self._silence_streak.pop(rid, None)
                if rid in self._sovereign:
                    self._sovereign.discard(rid)
                    self._counters.sovereign_rejoins += 1
                continue

            streak = self._silence_streak.get(rid, 0) + 1
            self._silence_streak[rid] = streak
            if streak >= SOVEREIGN_CONFIRM_TICKS:
                if rid not in self._sovereign:
                    self._sovereign.add(rid)
                    self._counters.sovereign_entries += 1
                self._counters.sovereign_ticks += 1

    @property
    def sovereign(self) -> tuple[str, ...]:
        """Ids currently operating alone, sorted so the wire order is stable."""
        return tuple(sorted(self._sovereign))

    def is_sovereign(self, robot_id: str) -> bool:
        return robot_id in self._sovereign

    def stats(self) -> dict:''',
    "detector method",
)

# --- 2. tightened envelope -----------------------------------------------
text = sub(
    text,
    """        want = proposal.speed_scale or 0.0
        if want <= 0.0:
            return proposal          # already stopped, nothing to veto
""",
    """        want = proposal.speed_scale or 0.0
        if want <= 0.0:
            return proposal          # already stopped, nothing to veto

        # X-01. A sovereign robot has heard nothing for half a second, so it can
        # no longer assume any peer will yield, and it has no idea whether the
        # space beyond its sensors is occupied. The standing rule of this file -
        # assume a peer will OCCUPY space, never that it will VACATE it - taken
        # to its limit means treating unknown space as occupied, which is
        # expressed here as a wider floor and a lower speed. Both are LOCAL: the
        # module constant HARD_STOP_M is untouched, so the fleet-wide safety rule
        # the baseline comparison rests on is unchanged.
        floor = HARD_STOP_M
        asked = want
        if rid in self._sovereign:
            floor = HARD_STOP_M + SOVEREIGN_MARGIN_M
            want = min(want, SOVEREIGN_SPEED_CAP)
""",
    "envelope setup",
)

text = sub(
    text,
    """                gap = segment_distance(mine, theirs)
                if gap >= HARD_STOP_M:
                    continue""",
    """                gap = segment_distance(mine, theirs)
                if gap >= floor:
                    continue""",
    "floor test",
)

text = sub(
    text,
    """            if fraction >= 1.0:
                # The negotiation's own decision is safe as proposed. This is the
                # overwhelmingly common case and it must pass through untouched,
                # so the ladder's reason string and utility terms reach the
                # Decision Inspector intact.
                self._veto_streak.pop(rid, None)
                return proposal""",
    """            if fraction >= 1.0:
                # The negotiation's own decision is safe as proposed. This is the
                # overwhelmingly common case and it must pass through untouched,
                # so the ladder's reason string and utility terms reach the
                # Decision Inspector intact.
                self._veto_streak.pop(rid, None)
                if candidate < asked:
                    # Only reachable while sovereign, where `want` was capped
                    # below what the negotiation asked for. The motion is safe,
                    # but returning the proposal verbatim would silently ignore
                    # the cap, so the cap is stated as its own verdict instead.
                    return Verdict(
                        robot_id=rid, kind=VerdictKind.SLOW,
                        reason=(
                            f"sovereign mode: isolated for "
                            f"{self._silence_streak.get(rid, 0)} ticks, speed "
                            f"capped at {SOVEREIGN_SPEED_CAP:.0%} and floor "
                            f"widened to {floor:.2f} m"
                        ),
                        speed_scale=candidate,
                        utility_terms=proposal.utility_terms,
                        winning_margin=proposal.winning_margin,
                    )
                return proposal""",
    "full-step branch",
)

text = sub(
    text,
    """                reason=(
                    f"safety monitor clamped to {fraction:.0%} of requested "
                    f"speed: {peer_id} at {gap:.2f} m, floor "
                    f"{HARD_STOP_M:.2f} m"
                ),""",
    """                reason=(
                    f"safety monitor clamped to {fraction:.0%} of requested "
                    f"speed: {peer_id} at {gap:.2f} m, floor "
                    f"{floor:.2f} m"
                    + (" (sovereign)" if rid in self._sovereign else "")
                ),""",
    "slow reason",
)

# --- 3. reporting ---------------------------------------------------------
text = sub(
    text,
    """            "failures_confirmed": c.failures_confirmed,
            "radio": radio,""",
    """            "failures_confirmed": c.failures_confirmed,
            "sovereign": {
                "entries": c.sovereign_entries,
                "ticks": c.sovereign_ticks,
                "rejoins": c.sovereign_rejoins,
                "robots_sovereign_now": len(self._sovereign),
                "robots": list(self.sovereign),
                "confirm_ticks": SOVEREIGN_CONFIRM_TICKS,
                "margin_m": SOVEREIGN_MARGIN_M,
                "speed_cap": SOVEREIGN_SPEED_CAP,
            },
            "radio": radio,""",
    "stats",
)

text = sub(
    text,
    """            "yield_streak": self._yield_streak.get(robot_id, 0),""",
    """            "yield_streak": self._yield_streak.get(robot_id, 0),
            "sovereign": robot_id in self._sovereign,
            "silence_streak": self._silence_streak.get(robot_id, 0),""",
    "explain",
)

ast.parse(text)
P.write_text(text)
print("swarm_policy.py detector/envelope/report patched OK")
