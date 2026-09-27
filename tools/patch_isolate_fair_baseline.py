"""Remove the one-sided-sweep bias from tools/diag_isolate.py.

The harness compared SwarmPolicy (tuned) against StopAndWaitPolicy running at
its UNTUNED default STUCK_TICKS = 30. diag_baseline_sweep.py showed the baseline
peaks at STUCK_TICKS = 8 (29 completions vs 19 at k=30), so every ablation run
through this harness inherited a ~50% handicap in SwarmPolicy's favour.

Standing rule this enforces: when tuning a parameter that BOTH policies possess,
the baseline must be swept over the same range in the same commit.
"""
import ast
import pathlib

PATH = pathlib.Path("tools/diag_isolate.py")

OLD_IMPORT = "from app.sim.policy import StopAndWaitPolicy, Verdict, VerdictKind"
NEW_IMPORT = OLD_IMPORT + """

# The baseline's own collision-free optimum, measured by diag_baseline_sweep.py
# (29 completions at k=8 versus 19 at the k=30 default). STUCK_TICKS is a class
# attribute precisely so it can be retuned without editing app/sim/policy.py.
BASE_STUCK_TICKS = 8
TunedStopAndWait = type(
    "TunedStopAndWait", (StopAndWaitPolicy,), {"STUCK_TICKS": BASE_STUCK_TICKS}
)"""

OLD_FACTORY = '"baseline": lambda s: StopAndWaitPolicy(),'
NEW_FACTORY = '"baseline": lambda s: TunedStopAndWait(),'


def main() -> None:
    text = PATH.read_text()
    if "BASE_STUCK_TICKS" in text:
        print("already applied")
        return
    for old, new in ((OLD_IMPORT, NEW_IMPORT), (OLD_FACTORY, NEW_FACTORY)):
        if old not in text:
            raise SystemExit(f"anchor not found: {old[:60]}")
        text = text.replace(old, new, 1)
    ast.parse(text)
    PATH.write_text(text)
    print("applied: diag_isolate baseline now STUCK_TICKS=8")


if __name__ == "__main__":
    main()
