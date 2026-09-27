"""Wire X-10 / N9 into the arbiter: authenticate, audit, contain, and GC.

Four joins, each of which was a half-built mechanism with no counterpart:

1. AUTHENTICATION. Every broadcast is signed and every received message is
   verified. A message that fails verification is DROPPED and its sender
   accused, rather than merely dropped - silently discarding hostile traffic
   makes an attack indistinguishable from a quiet radio.

2. BEHAVIOURAL AUDIT. Each robot compares what its neighbours CLAIM against
   what it can physically SEE (`observations`, supplied by the simulation as a
   stand-in for onboard perception). Disagreement beyond tolerance is an
   accusation, and only a quorum of independent accusers contains anyone.

3. ENFORCEMENT. A contained robot is cut off at the radio. The council decides,
   the radio enforces, the simulation stops the robot. Three separate concerns,
   kept separate on purpose.

4. RESERVATION GARBAGE COLLECTION. `ReservationManager.release_robot_reservations`
   and `FailureDetector.confirmed_failed` both already existed and nothing
   called one from the other. A confirmed-failed or contained robot therefore
   held its reserved space for the rest of the run - a permanent, silent loss of
   floor area that no counter would ever have shown. That join is made here.

The integrity layer is deliberately OFF by default (`integrity=False`). It is a
scenario feature the operator turns on, and the existing 458-test baseline plus
every recorded trace hash must be unaffected when it is off. A safety feature
that silently changes the behaviour of every other scenario is not free.
"""
import ast

POL = "app/coordination/swarm_policy.py"
src = open(POL).read()

# ---- imports ----------------------------------------------------------------
old = """    BoundedRadio,
    FailureDetector,"""
new = """    BoundedRadio,
    FailureDetector,"""
assert src.count(old) == 1

old = "class _Counters:"
new = "class _Counters:"
assert src.count(old) == 1

# add the integrity imports after the radio import block
old = """@dataclass
class _Counters:
    ticks: int = 0"""
new = """@dataclass
class _Counters:
    ticks: int = 0
    # Adversarial containment (X-10 / N9). Counted separately from failures
    # because a robot that is lying and a robot that is dead need completely
    # different responses, and a single "problem robots" number would hide that.
    messages_rejected: int = 0
    accusations_raised: int = 0
    robots_contained: int = 0
    reservations_reclaimed: int = 0"""
assert src.count(old) == 1
src = src.replace(old, new)

# ---- constructor ------------------------------------------------------------
old = """        weights: UtilityWeights = DEFAULT_WEIGHTS,
        monitor: bool = True,
    ) -> None:"""
new = """        weights: UtilityWeights = DEFAULT_WEIGHTS,
        monitor: bool = True,
        integrity: bool = False,
        reservations=None,
    ) -> None:"""
assert src.count(old) == 1
src = src.replace(old, new)

old = """        self.radio = BoundedRadio(rng=self._rng, profile=link, radius_m=radius_m)
        self.detector = FailureDetector()
        self.weights = weights
        self.monitor_enabled = monitor
"""
new = """        self.radio = BoundedRadio(rng=self._rng, profile=link, radius_m=radius_m)
        self.detector = FailureDetector()
        self.weights = weights
        self.monitor_enabled = monitor

        # Adversarial containment (X-10 / N9). OFF by default: it is a scenario
        # the operator turns on, and turning it on must be the ONLY thing that
        # changes behaviour. With integrity=False not one byte of the message
        # path differs, so every previously recorded trace hash still verifies.
        self.integrity_enabled = integrity
        self.auth = MessageAuthenticator()
        self.council = SentinelCouncil()
        # Ground-truth sightings for the current tick, handed in by the
        # simulation via observe(). A witness must compare a claim against
        # something it did not get from the claimant, or the check is circular.
        self._sightings: dict[str, dict] = {}
        # Optional. When present, a robot that is confirmed failed or contained
        # has its reserved space reclaimed. Optional rather than constructed
        # here because the reservation manager is shared with the auction layer
        # and must have exactly one owner.
        self.reservations = reservations
        self._reclaimed: set[str] = set()
"""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(POL, "w").write(src)
print("stage 1 (counters, constructor) OK")
