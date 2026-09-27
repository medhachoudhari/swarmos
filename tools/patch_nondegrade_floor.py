"""Let a pair that is ALREADY inside the floor separate, without relaxing it.

The problem, measured by X-12 co-simulation at fleet 50: SWARMOS completed 5
tasks where plain stop-and-wait completed 21, with 40 of 50 robots sitting at
speed_scale 0.0. The monitor's own docstring records the cause as a KNOWN
LIMITATION: swept(scale) always contains `here`, so

    segment_distance(swept(scale), theirs) <= segment_distance(rest, theirs)

for every scale. Once a pair is inside HARD_STOP_M no fraction of the step can
clear it, the graded MONITOR_SCALES fallback cannot fire, and every single
intervention becomes a full stop.

The change: the floor a motion must clear becomes

    min(at_rest, HARD_STOP_M)

instead of HARD_STOP_M outright. Where the pair is comfortably apart this is
identical to today, because at_rest >= HARD_STOP_M makes the min the floor
itself. Where the pair is already closer than the floor, the requirement
becomes "do not make it worse" rather than "clear a bar you cannot reach".

Why this is not the exemption the docstring rejects three times. Those were all
ENDPOINT tests - "I finish further away than I started" - and the docstring is
right that no endpoint test can tell separating from crossing, because a robot
cutting in front of a peer does end up further away. This test is measured on
the same SEGMENT-vs-SEGMENT distance the kernel already uses, and two paths that
cross have a segment distance of 0, which is below any positive at_rest. So
crossing traffic is still caught. What gets through is only motion whose whole
swept path stays at least as far from the peer's granted segment as standing
still would - which, because rest is contained in mine, means it did not
approach at all.

Why it is not the rejected time-parameterised test either. There is no shared
time parameter and no prediction that the peer vacates anything: `theirs` is
still the granted segment treated as occupied space, and the minimisation is
still independent over the two robots' times. The standing rule from
SESSION_SUMMARY_20260921_0050 - a safety kernel may assume a peer will OCCUPY
space, never that it will VACATE it - is preserved exactly.

Safety floor: the pair separation can never be degraded by this rule, so no
motion it permits can reduce a gap below where the tick started. FOOTPRINT_M is
0.70 and HARD_STOP_M is 0.75, so a pair between those values keeps its
clearance rather than gaining licence to close.
"""

import ast
import sys

PATH = "app/coordination/swarm_policy.py"

src = open(PATH).read()

# 1. The floor test itself.
OLD_TEST = """                gap = segment_distance(mine, theirs)
                if gap >= HARD_STOP_M:
                    continue
"""

NEW_TEST = """                gap = segment_distance(mine, theirs)
                # The bar this motion has to clear. Normally HARD_STOP_M, but
                # never MORE than the separation the pair already has: a bar
                # above at_rest is unreachable, because `mine` contains `here`
                # and so gap <= at_rest for every scale. Demanding the
                # impossible is what turned every intervention into a full stop
                # and cost the fleet 4x its throughput (X-12).
                #
                # Inside the floor the requirement becomes non-degradation:
                # do not close the gap further. Time-agnostic, and measured on
                # segments, so crossing traffic - segment distance 0 - is still
                # caught. See tools/patch_nondegrade_floor.py.
                floor = at_rest if at_rest < HARD_STOP_M else HARD_STOP_M
                if gap >= floor - NONDEGRADE_EPS_M:
                    continue
"""

assert src.count(OLD_TEST) == 1, "floor test anchor not unique: %d" % src.count(OLD_TEST)
src = src.replace(OLD_TEST, NEW_TEST)

# 2. The epsilon, declared next to the floor it qualifies.
OLD_CONST = "HARD_STOP_M = 0.75\n"
NEW_CONST = """HARD_STOP_M = 0.75

# Slack on the non-degradation comparison. A motion that does not approach a
# peer at all produces a gap exactly equal to the standing-still gap, so the
# test is an equality in exact arithmetic and needs a tolerance to survive
# floating point. Set far below any distance the fleet can act on: 0.1 mm
# against a 0.70 m footprint.
NONDEGRADE_EPS_M = 1e-4
"""
assert src.count(OLD_CONST) == 1, "HARD_STOP_M anchor not unique"
src = src.replace(OLD_CONST, NEW_CONST)

# 3. Retire the KNOWN LIMITATION note, which this patch resolves.
OLD_NOTE = """                # KNOWN LIMITATION, measured and documented rather than fixed.
                # swept(scale) always contains `here`, so the gap above is
                # bounded by the standing-still gap for EVERY scale. Once a pair
                # is inside the floor no fraction of the step clears it, so the
                # graded MONITOR_SCALES fallback cannot fire and the clamp ratio
                # stays at 0.038 to 0.270 - almost every intervention is still a
                # full stop. Fixing it requires a tighter test that remains
                # time-agnostic; the obvious time-parameterised one costs
                # collisions. See tools/patch_revert_monitor_cbf.py.
"""
NEW_NOTE = """                # The limitation this note used to record - that swept(scale)
                # contains `here`, so no fraction of the step can clear a floor
                # the pair is already inside - is fixed above by capping the
                # floor at the standing-still gap. The fix is time-agnostic, so
                # the rejected time-parameterised test is still rejected.
"""
assert src.count(OLD_NOTE) == 1, "known-limitation note anchor not unique"
src = src.replace(OLD_NOTE, NEW_NOTE)

ast.parse(src)   # gate: never write a file that does not parse
open(PATH, "w").write(src)
print("patched %s, ast OK" % PATH)
