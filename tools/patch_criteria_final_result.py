"""Fill in the 'Final powered result' section of the criteria document.

Numbers come verbatim from reports/criteria_after_envelope_fix.log, the
9000-tick 9-seed paired run executed after C1 defect 2 was fixed. Also tightens
the C1 verdict wording now that the outcome is known instead of pending.
"""
import io
import sys

DOC = "docs/SUCCESS_CRITERIA_VERIFICATION.md"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 match, found %d" % (label, count)
    return text.replace(old, new)


OLD_VERDICT = """See the "Final powered result" section below, which is filled in from
`reports/criteria_after_envelope_fix.log`. The honest summary of C1 is not
"we met the criterion" - it is "the criterion was not met, the measurement that
said it was had been run too short, two real defects were behind it, both were
found, root-caused and fixed, and the third element is that the fix is now
pinned by tests that fail on the old code."
"""

NEW_VERDICT = """**C1 is MET as of the post-defect-2 measurement: 0 collisions across 27 paired
9000-tick runs** (`reports/criteria_after_envelope_fix.log`, quoted in full in
the "Final powered result" section below). That statement is only worth what the
route to it is worth, so the route is stated plainly: the criterion was *not*
met when it was first measured honestly, the earlier measurement that said it
was had been run too short to expose the failures, two real defects were behind
the 7 collisions, both were root-caused to a specific tick and a specific line,
both were fixed, and both fixes are now pinned by tests that fail on the old
code.
"""

OLD_PENDING = """Pending: filled in from `reports/criteria_after_envelope_fix.log` on completion
of the post-defect-2 run (9000 ticks, 9 seeds, both arms).
"""

NEW_FINAL = """Reproduced with `tools/verify_criteria_powered.py 9000 9`; 3 scenarios x 9 seeds
x 2 arms = 54 runs, 27 pairs, wall clock 2319.9 s. Log:
`reports/criteria_after_envelope_fix.log`.

```
C1 zero collisions in the SwarmOS arm: 0  PASS
   baseline arm collisions (control, expected > 0): 0
--------------------------------------------------------------------------
C2 paired reduction in avg_completion_s, n=27 paired runs
  mean            : -19.3 pct
  std dev         :  42.2 pct
  95 pct CI       : [-36.0, -2.6] pct
  target          : >= 20 pct
  tasks completed : min=1  median=10  max=28  (per arm per run)
  verdict         : NOT MET - the whole interval sits below the bar
  elapsed         : 2319.9 s
```

### What this says

- **C1: PASS.** Zero collisions, zero overlap ticks, in the arm that previously
  produced 7 collisions. No `SwarmOS collision run:` line appears anywhere in the
  log - the collision reporter printed nothing because there was nothing to
  report. The two per-seed regression tests (`blocked_aisle` 29 and 17) lock the
  two specific ticks that used to fail.
- **C1 control caveat, unchanged.** The stop-and-wait baseline is also at 0. C1
  is necessary, not differentiating: it shows negotiation, containment and
  sovereign fallback did not cost the safety property.
- **C2: still NOT MET, and the point estimate moved further negative**, from
  -13.7 pct to **-19.3 pct**, with the CI widening to [-36.0, -2.6] pct. The
  interval still lies entirely below zero, so the direction is not in doubt on
  this statistic.

### Why C2 got worse when a safety bug was fixed

This is the expected direction, and it is worth saying out loud rather than
hiding. Defect 2 was the arbiter under-estimating a robot's own one-tick reach,
so it was granting speed it should have withheld. Making the bound sound means
the arbiter now withholds that speed. Throughput paid for safety - which is
precisely the trade a binding safety arbiter exists to make. A number that had
improved after this fix would have been evidence the fix was not doing anything.

It remains true that the statistic itself is unsound for a cross-arm comparison
(see the survivorship-bias finding above): `avg_completion_s` averages only the
tasks that finished, and the two arms do not finish the same tasks. The honest
reading of C2 today is "not met on a biased statistic, and not yet measured on an
unbiased one", and fixing the statistic is the first roadmap item - not because
it is likely to flip the sign, but because the current number cannot support
either conclusion.
"""


def main():
    text = io.open(DOC, encoding="utf-8").read()
    text = sub(text, OLD_VERDICT, NEW_VERDICT, "C1 verdict")
    text = sub(text, OLD_PENDING, NEW_FINAL, "final result")
    io.open(DOC, "w", encoding="utf-8").write(text)
    bad = sorted({c for c in text if ord(c) > 127})
    print("written; non-ascii in doc:", bad)
    print("lines:", text.count("\n") + 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
