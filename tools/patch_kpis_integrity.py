"""Surface the integrity block in kpis().

The policy computes stats()["integrity"] every tick, but kpis() never read it,
so nothing downstream - not the UI, not the benchmark report, not the operator
- could see how many messages were rejected or who was contained. The whole
point of the KPI method's docstring is that the number on screen and the
number in the report cannot drift apart; a metric that never leaves the policy
object is outside that guarantee entirely.

None (not {} and not zeros) when the layer is off: a missing value must render
as "--" rather than as a confident zero. Claiming "0 rejected" when the
detector was never armed would be fabricated data.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
path = ROOT / "app/sim/engine.py"
src = path.read_text()

old = """            "advisory": self.advisory_stats(),
            "compute": self.clock.compute_stats(),"""
new = """            "advisory": self.advisory_stats(),
            "integrity": self._integrity_stats(),
            "compute": self.clock.compute_stats(),"""
assert src.count(old) == 1, src.count(old)
src = src.replace(old, new)

anchor = """    def kpis(self, compute_ms: float = 0.0) -> dict:"""
helper = '''    def _integrity_stats(self):
        """The coordination layer's integrity block, or None when it is off.

        None rather than a dict of zeros: the operator must be able to tell
        "nothing was rejected" apart from "nothing was watching". A zero in
        place of an unknown is the one kind of lie this dashboard cannot tell,
        since the entire feature it describes is about detecting lies.
        """
        stats = getattr(self.policy, "stats", None)
        if not callable(stats):
            return None
        block = stats().get("integrity")
        if not isinstance(block, dict) or not block.get("enabled"):
            return None
        return block

'''
assert src.count(anchor) == 1
src = src.replace(anchor, helper + anchor)

ast.parse(src)
path.write_text(src)
print("patched app/sim/engine.py")
