"""Replace the session summary's 'Open item' with the completed measurement."""
import io
import sys

DOC = "SESSION_SUMMARY_20260922_0040_c1_two_defects_root_cause_and_fix.md"

OLD = """## Open item

`reports/criteria_after_envelope_fix.log` (9000 ticks, 9 seeds, both arms) was
still running at the time of writing; the expected line is
`C1 zero collisions in the SwarmOS arm: 0 PASS`. The "Final powered result"
section of the criteria document is the placeholder to fill from it.
"""

NEW = """## Closed: the confirmation measurement

`reports/criteria_after_envelope_fix.log` finished in 2319.9 s (9000 ticks,
9 seeds, 3 scenarios, both arms, 27 pairs):

```
C1 zero collisions in the SwarmOS arm: 0  PASS
   baseline arm collisions (control, expected > 0): 0
C2 paired reduction in avg_completion_s, n=27 paired runs
  mean            : -19.3 pct
  std dev         :  42.2 pct
  95 pct CI       : [-36.0, -2.6] pct
  target          : >= 20 pct
  verdict         : NOT MET - the whole interval sits below the bar
```

- **C1 PASS.** 7 collisions -> 0, and no `SwarmOS collision run:` line anywhere
  in the log. Both defects are pinned by tests that fail on the old code.
- **C2 still NOT MET, and the mean moved from -13.7 pct to -19.3 pct.** That is
  the expected direction: defect 2 was the arbiter under-estimating a robot's own
  one-tick reach and therefore granting speed it should have withheld, so a sound
  bound costs throughput. A C2 that had *improved* after this fix would have been
  evidence the fix was inert.
- The statistic itself remains unsound across arms (survivorship bias in
  `avg_completion_s`); re-scoring C2 on an unbiased measure is roadmap item 1.

Everything is now consistent: `docs/SUCCESS_CRITERIA_VERIFICATION.md` carries the
final numbers in its "Final powered result" section, and slide 18 of the master
spec deck shows -19.3 pct / [-36.0, -2.6] (deck re-verified at 25 slides,
flagged=0, non-ascii []).

## Remaining work, unchanged

1. Re-score C2 on an equal-completion-count or `tasks_per_min` statistic.
2. Raise task supply so `blocked_aisle` is not exhausted inside the run window.
3. Consider whether the peer `granted` segments should also use `_step_envelope`
   - they intentionally do not today, because over-assuming peer motion already
   costs 31 percent of robot-ticks to phantom motion.
"""


def main():
    text = io.open(DOC, encoding="utf-8").read()
    n = text.count(OLD)
    assert n == 1, "open item: expected 1 match, found %d" % n
    text = text.replace(OLD, NEW)
    io.open(DOC, "w", encoding="utf-8").write(text)
    print("written; non-ascii:", sorted({c for c in text if ord(c) > 127}))
    print("lines:", text.count("\n") + 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
