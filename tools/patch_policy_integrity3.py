"""Stage 3: enrolment, and the engine-side hookup.

The enrolment bug this fixes, recorded because it is instructive: with the
integrity layer on and nothing ever calling `auth.enrol()`, EVERY sender is an
unknown sender, so every robot accuses every peer of impersonation, quorum is
reached instantly for all of them, and the entire fleet quarantines itself on
tick one. The containment mechanism would have destroyed the fleet it exists to
protect - which is precisely the failure mode the quorum rule is meant to guard
against, arriving through the door nobody was watching.
"""
import ast

POL = "app/coordination/swarm_policy.py"
src = open(POL).read()

old = """    ) -> None:
        self.radio.tick_begin(tick)
        self.radio.set_positions("""
new = """    ) -> None:
        self.radio.tick_begin(tick)
        if self.integrity_enabled:
            # Enrolment is refreshed every tick and is idempotent. It must
            # happen BEFORE any verification: with an empty roster every sender
            # is unknown, every robot accuses every peer of impersonation, and
            # the whole fleet quarantines itself on tick one. A containment
            # mechanism that can wipe out the fleet it protects is worse than
            # none, so the roster is derived from the fleet the simulation
            # actually reports rather than configured separately.
            self.auth.enrol(states)
        self.radio.set_positions("""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(POL, "w").write(src)
print("policy stage 3 OK")

# ---------------------------------------------------------------- engine side
ENG = "app/sim/engine.py"
src = open(ENG).read()

old = """        states = self.observed_states()"""
assert src.count(old) == 1, src.count(old)
new = """        states = self.observed_states()
        # Hand the arbiter this tick's ground-truth sightings, if it wants them.
        # Guarded with hasattr because the baseline policy is a different class
        # entirely and must not be forced to grow an integrity API it has no use
        # for - the comparison is only fair if the baseline stays the baseline.
        if hasattr(self.policy, "observe"):
            self.policy.observe(self.observations())"""
src = src.replace(old, new)

old = """        self._apply_onboard_brake()
"""
new = """        # Enforce whatever the coordination layer has contained. Read back from
        # the policy rather than pushed by it, so the simulation remains the one
        # authority on robot state (law 1) and coordination cannot reach in.
        council = getattr(self.policy, "council", None)
        if council is not None:
            self.apply_containment(council.contained)

        self._apply_onboard_brake()
"""
assert src.count(old) == 1
src = src.replace(old, new)

ast.parse(src)
open(ENG, "w").write(src)
print("engine stage 3 OK")
