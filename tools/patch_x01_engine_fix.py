"""X-01 fix. Move the blackout deadline map into the real constructor.

It was attached to set_policy(), which normal construction never calls, so
_expire_blackouts() raised AttributeError on the first step.
"""
import ast
import pathlib

P = pathlib.Path("app/sim/engine.py")
t = P.read_text()


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, f"{label}: expected 1 match, found {n}"
    return text.replace(old, new)


BAD = '''    def set_policy(self, policy: CoordinationPolicy) -> None:
        """Swap the arbiter. Used to hand control from the stub to M4."""
        self.policy = policy
        # X-01. tick at which each silenced robot's radio comes back. Engine
        # state rather than radio state, because the radio's job is to model
        # reachability, not to schedule the operator's faults.
        self._blackout_until: dict[str, int] = {}
'''
GOOD = '''    def set_policy(self, policy: CoordinationPolicy) -> None:
        """Swap the arbiter. Used to hand control from the stub to M4."""
        self.policy = policy
'''
t = sub(t, BAD, GOOD, "strip from set_policy")

OLD = '''        self.policy: CoordinationPolicy = policy if policy is not None else NoOpPolicy()
'''
NEW = '''        self.policy: CoordinationPolicy = policy if policy is not None else NoOpPolicy()

        # X-01. tick at which each silenced robot's radio comes back. Engine
        # state rather than radio state, because the radio's job is to model
        # reachability, not to schedule the operator's faults.
        self._blackout_until: dict[str, int] = {}
'''
t = sub(t, OLD, NEW, "add to __init__")

ast.parse(t)
P.write_text(t)
print("patched")
