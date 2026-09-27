"""X-01 step 2: sovereign agent mode in the arbiter (constants, counters, state).

CONTRACT
  A robot that loses contact with every peer must keep working safely and
  alone, then rejoin cleanly.

MECHANISM
  Entry   total isolation - zero fresh peers in its own inbox - sustained for
          SOVEREIGN_CONFIRM_TICKS (the same 500 ms confirmation window the
          failure detector uses), while the robot itself is still healthy.
  Effect  it keeps its task and keeps moving, but under a TIGHTENED envelope:
          the safety floor is widened by SOVEREIGN_MARGIN_M and its speed is
          capped at SOVEREIGN_SPEED_CAP. It may no longer assume anyone will
          yield, so it treats unknown space as potentially occupied. This is the
          standing rule of this file applied to the limit case - a safety kernel
          may assume a peer will OCCUPY space, never that it will VACATE it -
          and with an empty inbox every direction is unknown space.
  Exit    the first tick any fresh peer reappears. Rejoin is immediate and
          needs no handshake, because the tightened envelope is strictly more
          conservative than the normal one: a robot leaving sovereign mode is
          relaxing a constraint, which can never create a new conflict for a
          peer that was already planning around it.

WHY NOT SIMPLY STOP
  Stopping is trivially safe and useless: in a warehouse with steel racking a
  robot that halts on every radio shadow blocks an aisle for everyone, which
  converts a local comms fault into a fleet-wide throughput fault. The claim
  being made is that useful work continues, and that is only interesting if the
  robot still moves.

WHY THIS CANNOT PERTURB EXISTING REPLAYS
  Measured before writing any of it: tools/probe_isolation.py reports ZERO
  zero-peer robot-ticks in 30,000 robot-ticks of a normal 50-robot run. Entry
  additionally requires SOVEREIGN_CONFIRM_TICKS consecutive such ticks. With no
  blackout injected the detector never arms, so trace_hash is unchanged - and
  there is a test that asserts exactly that rather than trusting this paragraph.
"""
import ast
import pathlib

P = pathlib.Path("app/coordination/swarm_policy.py")
text = P.read_text()


def sub(t, old, new, label):
    assert t.count(old) == 1, f"{label}: expected 1 match, got {t.count(old)}"
    return t.replace(old, new)


# --- constants -------------------------------------------------------------
# The bare string "HARD_STOP_M = 0.75" also appears inside the _monitor
# docstring, so anchor on the definition plus the comment that follows it.
text = sub(
    text,
    """HARD_STOP_M = 0.75

# Inside this band the encounter is a genuine conflict and goes to contest.""",
    """HARD_STOP_M = 0.75

# ---------------------------------------------------------------------------
# X-01 sovereign agent mode
# ---------------------------------------------------------------------------
# Ticks of TOTAL isolation - not one fresh peer in the inbox - before a healthy
# robot declares itself sovereign. Five ticks is 500 ms at 10 Hz, deliberately
# the same confirmation window the failure detector uses for the mirror-image
# question ("has that peer died?"), because the two judgements are made from the
# same evidence and disagreeing about how long silence must last before it means
# something would be indefensible.
SOVEREIGN_CONFIRM_TICKS = 5

# Extra clearance a sovereign robot demands, on top of HARD_STOP_M. 0.35 m is
# one robot radius: enough that a peer it cannot hear could be sitting exactly
# at the edge of its own footprint and still be cleared.
SOVEREIGN_MARGIN_M = 0.35

# Speed ceiling while sovereign, as a fraction of the requested step. Halving
# the step doubles the time available to react to something that appears with no
# radio warning at all, which is the only defence left once coordination is
# gone.
SOVEREIGN_SPEED_CAP = 0.5

# Inside this band the encounter is a genuine conflict and goes to contest.""",
    "constants",
)

# --- counters --------------------------------------------------------------
text = sub(
    text,
    """    failures_confirmed: int = 0""",
    """    failures_confirmed: int = 0
    # X-01. Counted separately from failures and containments because a robot
    # that has lost its radio is neither broken nor hostile - it is working, and
    # a report that lumped it in with either would misinform the operator.
    sovereign_entries: int = 0
    sovereign_ticks: int = 0
    sovereign_rejoins: int = 0""",
    "counters",
)

# --- state -----------------------------------------------------------------
text = sub(
    text,
    """        self._veto_streak: dict[str, int] = {}""",
    """        self._veto_streak: dict[str, int] = {}
        # X-01. Consecutive ticks each robot has heard nothing, and the set that
        # has crossed SOVEREIGN_CONFIRM_TICKS and is therefore operating alone.
        self._silence_streak: dict[str, int] = {}
        self._sovereign: set[str] = set()""",
    "state",
)

ast.parse(text)
P.write_text(text)
print("swarm_policy.py constants/counters/state patched OK")
