"""Correct the MONITOR_STUCK_TICKS comment: the "+5.3% win" was an artefact.

patch_stuck_ticks_4.py committed k=4 on the strength of a sweep that beat a
baseline scoring 19 completions. That baseline was running its own
StopAndWaitPolicy.STUCK_TICKS at the untuned default of 30. Sweeping the baseline
over the SAME range (tools/diag_baseline_sweep.py) shows it improves far more
than SWARMOS does:

    k     baseline   swarmos   delta
    2       25         14      -44.0%
    3       27         19      -29.6%
    4       28         20      -28.6%
    5       27         18      -33.3%
    6       28         18      -35.7%
    8       29         17      -41.4%
   12       28         18      -35.7%
   20       20         15      -25.0%
   30       19         13      -31.6%

The arbiter loses on EVERY row. Best-versus-best, both collision-free, the
baseline peaks at 29 (k=8) and SWARMOS at 20 (k=4): -31.0%.

So the honest reading is that recovery latency was never a SWARMOS advantage at
all - it was an unfair comparison. k=4 is still retained because it is genuinely
the best value FOR THIS POLICY, and running a policy at a knowingly inferior
setting would be its own form of dishonesty. But the comment must not imply a win
that does not exist.
"""
import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "app" / "coordination" / "swarm_policy.py"

OLD = """#         4     20     +5.3%         0/0/0      5466   <-- chosen"""
NEW = """#         4     20     +5.3%         0/0/0      5466   <-- chosen"""

OLD_FAIR = """# The fairness argument for matching the baseline is NOT abandoned. It is instead
# discharged by sweeping StopAndWaitPolicy.STUCK_TICKS over the same range in the
# same harness and quoting the headline improvement against the baseline at ITS
# own optimum. A faster escape hatch than the baseline's would otherwise win the
# benchmark by changing the benchmark.
MONITOR_STUCK_TICKS = 4"""

NEW_FAIR = """# CORRECTION, and it matters more than the table above. The "+5.3%" column is
# measured against a baseline running its own StopAndWaitPolicy.STUCK_TICKS at the
# untuned default of 30. That is not a fair fight. Sweeping the BASELINE over the
# same range (tools/diag_baseline_sweep.py) shows it benefits far more from the
# same tuning than SWARMOS does:
#
#      k   baseline   swarmos    delta
#      2       25        14     -44.0%
#      3       27        19     -29.6%
#      4       28        20     -28.6%
#      5       27        18     -33.3%
#      6       28        18     -35.7%
#      8       29        17     -41.4%
#     12       28        18     -35.7%
#     20       20        15     -25.0%
#     30       19        13     -31.6%
#
# The arbiter loses on EVERY row. Best-versus-best, both collision-free, the
# baseline peaks at 29 completions (k=8) against SWARMOS at 20 (k=4), so the
# honest headline is -31.0%, not +5.3%. Recovery latency was never a SWARMOS
# advantage; the apparent win was an artefact of handicapping the baseline.
#
# k=4 is nonetheless KEPT, for two reasons. It is the best value for this policy,
# and deliberately running a policy at a setting known to be worse would be its
# own kind of dishonesty. Second, the remaining gap is now known to sit in the
# safety kernel's pessimism rather than in its recovery: with the kernel disabled
# the same ladder reaches +94.7%, but with 47-74 collisions. The whole engineering
# problem is to recover that throughput WITHOUT reintroducing contact, and no
# amount of threshold tuning will do it.
MONITOR_STUCK_TICKS = 4"""


def main() -> int:
    text = SRC.read_text()
    if "CORRECTION, and it matters more" in text:
        print("already applied")
        return 0
    if OLD_FAIR not in text:
        print("ERROR: anchor not found", file=sys.stderr)
        return 1
    out = text.replace(OLD_FAIR, NEW_FAIR, 1)
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print(f"ERROR: does not parse ({exc})", file=sys.stderr)
        return 1
    SRC.write_text(out)
    print("applied: corrected the fairness claim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
