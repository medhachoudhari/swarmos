"""X-01 step 1: give the radio a per-robot blackout switch.

Quarantine (X-10) already exists but means something different: the FLEET has
decided to cut a liar off. A blackout is a hardware or environment fault - the
antenna is jammed, or the robot has driven behind a steel rack - and it is
symmetric: the robot neither hears nor is heard. Reusing quarantine for it
would make an attack and a dead antenna indistinguishable in the reports, which
is the one thing an operator must always be able to tell apart.

Silenced hops are charged to `dropped` rather than to a new counter, because a
silenced hop IS a drop and adding a key would change the shape of the radio
stats dict that existing tests and the frontend already consume.
"""
import ast
import pathlib

P = pathlib.Path("app/coordination/radio.py")
text = P.read_text()


def sub(t, old, new, label):
    assert t.count(old) == 1, f"{label}: expected 1 match, got {t.count(old)}"
    return t.replace(old, new)


text = sub(
    text,
    """        # Robots whose traffic is discarded on sight (X-10 rogue containment).
        self._quarantined: set[str] = set()""",
    """        # Robots whose traffic is discarded on sight (X-10 rogue containment).
        self._quarantined: set[str] = set()
        # Robots whose radio is DEAD rather than distrusted (X-01 blackout).
        # Deliberately a separate set from _quarantined: quarantine is a
        # judgement the fleet makes and can lift, a blackout is a fault the
        # robot is suffering. Collapsing them would let an attack hide behind a
        # broken antenna in the reports.
        self._silenced: set[str] = set()""",
    "silenced set",
)

text = sub(
    text,
    """    def degree(self) -> dict[str, int]:""",
    """    # ------------------------------------------------------------------
    # radio blackout (X-01)
    # ------------------------------------------------------------------
    def silence(self, robot_id: str) -> None:
        \"\"\"Cut one robot's radio in BOTH directions.

        Symmetry is the point. A one-way cut would leave the robot still
        hearing peers and so still able to coordinate, which is not the failure
        being modelled: a jammed or shadowed antenna neither transmits nor
        receives, and that is precisely the case sovereign mode must survive.
        \"\"\"
        self._silenced.add(robot_id)

    def restore(self, robot_id: str) -> bool:
        \"\"\"Bring a silenced radio back. Returns whether one was actually out.\"\"\"
        was_out = robot_id in self._silenced
        self._silenced.discard(robot_id)
        return was_out

    def is_silenced(self, robot_id: str) -> bool:
        return robot_id in self._silenced

    @property
    def silenced(self) -> tuple[str, ...]:
        return tuple(sorted(self._silenced))

    def degree(self) -> dict[str, int]:""",
    "silence api",
)

# Receiving side: a silenced robot is not a neighbour of anyone, which removes
# it from every fan-out without touching the send paths.
text = sub(
    text,
    """            if rid == robot_id or rid in self._quarantined:
                continue""",
    """            if rid == robot_id or rid in self._quarantined:
                continue
            # A silenced peer cannot hear this robot, so it is not a neighbour.
            # Filtering here rather than in _deliver keeps the `reached` count
            # in broadcast() honest: nothing was reached, so nothing is counted.
            if rid in self._silenced:
                continue""",
    "neighbours filter",
)

# Sending side: a silenced robot's own emissions go nowhere.
text = sub(
    text,
    """        self.stats.offered += 1
        sender = msg.sender_id
        if sender in self._quarantined:
            self.stats.quarantined += 1
            return 0""",
    """        self.stats.offered += 1
        sender = msg.sender_id
        if sender in self._quarantined:
            self.stats.quarantined += 1
            return 0
        if sender in self._silenced:
            # Charged as a drop, not as a quarantine: the message was offered
            # and lost to a fault, which is exactly what `dropped` means.
            self.stats.dropped += 1
            return 0""",
    "broadcast gate",
)

ast.parse(text)
P.write_text(text)
print("radio.py patched OK")
