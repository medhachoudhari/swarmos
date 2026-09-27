"""X-01 fix. Prune the sovereign set for robots that vanish from the roster.

observed_states() omits FAILED robots entirely - their silence IS the failure
signal - so `ids` never mentions them and the detector loop never visited them.
A robot that died while sovereign therefore stayed sovereign for ever, which
would have shown a dead robot as "running alone" in the UI and in the KPIs.

The loop now walks the roster plus anyone the detector is still tracking, so a
disappearance is handled by exactly the same branch as an explicit FAILED
status: dropped silently, and NOT counted as a rejoin.
"""
import ast
import pathlib

P = pathlib.Path("app/coordination/swarm_policy.py")
t = P.read_text()


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected 1 match, found {n}"
    return text.replace(old, new)


OLD = '''        A FAILED robot is dropped from the set silently and is NOT counted as a
        rejoin. It did not rejoin anything - it died - and inflating the rejoin
        count with corpses would make the recovery claim unfalsifiable.
        """
        for rid in ids:
            me = states.get(rid)
'''
NEW = '''        A FAILED robot is dropped from the set silently and is NOT counted as a
        rejoin. It did not rejoin anything - it died - and inflating the rejoin
        count with corpses would make the recovery claim unfalsifiable.

        The walk covers the roster PLUS anyone still being tracked, because
        observed_states() omits a failed robot altogether rather than reporting
        it as FAILED. Walking `ids` alone would leave such a robot marked
        sovereign for the rest of the run - a corpse displayed as "running
        alone", which is the most misleading state the UI could show.
        """
        tracked = sorted(set(ids) | self._sovereign | set(self._silence_streak))
        for rid in tracked:
            me = states.get(rid)
'''
t = sub(t, OLD, NEW, "prune loop")

ast.parse(t)
P.write_text(t)
print("policy patched")

T = pathlib.Path("tests/test_sovereign.py")
u = T.read_text()
u = sub(u, 'robot.as_wire()["s"]', 'robot.as_dict()["s"]', "as_dict")
ast.parse(u)
T.write_text(u)
print("test patched")
