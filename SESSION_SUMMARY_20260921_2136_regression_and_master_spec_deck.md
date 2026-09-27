# Session summary - 2026-09-21 21:36 - regression gate 570 and the master specification deck

## What this leg completed

Two deliverables, both from `NEXT_PLAN_20260921.md:89-92`, which named the
remaining Block E work as *"explicit verification of the two stated success
criteria plus the master specification deck"*. The criteria verification landed
last leg as `d300e44`. This leg closed the other half.

### 1. Full regression gate re-established at 570

```
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest tests/ -q
-> 570 passed in 69.89s
```

554 prior plus the 16 new X-23/X-24/X-25 receipts. No skips, no xfail, no
ignores. The 16 new tests did not disturb anything else, which was the specific
risk worth checking - they touch `FailureDetector`, `ReservationManager`,
`BoundedRadio` and `SwarmPolicy`, all of which other suites also exercise.

### 2. Master specification deck - 24 slides

`docs/gen_master_spec_pptx.py` generates
`SWARMOS_Master_Specification_SIH26123.pptx`.

The generator imports its theme and layout helpers from
`docs/gen_team_plan_pptx.py` rather than redefining them. That is deliberate:
two decks with two copies of the palette drift apart within a week, and a
visual inconsistency between the team deck and the spec deck is exactly the
kind of thing that reads as unfinished. It adds only two colours the team deck
lacks - TEAL `#4FB3A6`, taken from the UI's SOVEREIGN state colour so the deck
and the running product agree, and ORANGE for M6.

Three new layout primitives were written for this deck:

* `title_slide(prs)` - the cover, with four KPI cards.
* `two_col(...)` - two labelled bordered panels side by side, used wherever the
  content is genuinely a pair (as-published vs what-it-means, specification vs
  why, claim vs do-not-claim).
* `flow_row(...)` - a left-to-right row of boxes with plain ASCII `>` arrows
  between them, used for the architecture, the one-tick pipeline and the N9
  containment sequence.

Slide order: cover, the problem as SIH26123 states it, what SWARMOS is, the
four architectural laws, system architecture, frozen conventions, then one
slide per module (M5, M4, the one-tick pipeline, M3, M2, M1, M6), the novelty
register, N9, X-01, the X-23/24/25 receipts, the measured success criteria, the
verification evidence table, the six-minute demo script, the expected-questions
table, claim vs do-not-claim, the roadmap, and a closing summary.

## Verification performed on the deck

Because the UI and the rendered deck cannot be inspected from this shell, the
deck was checked programmatically:

* 24 slides, confirmed by reading the saved file back with `python-pptx`.
* **No empty slide** and **no slide over 2400 characters** - the two failure
  modes of a generated deck. All 24 came back clean.
* **Zero non-ASCII characters** anywhere in the deck text or table cells. The
  scan returned an empty set. This matters because smart quotes and en-dashes
  are what make a generated deck look machine-made.

## The editorial decision worth recording

Slide 18 is titled "Success criteria - measured" and states plainly that C1
passes and **C2 does not**: +2.3 percent mean against a 20 percent bar, with
the -47.8 to +57.9 percent spread and its cause (1 to 16 completed tasks per
run) on the slide itself. Slide 22 is a two-column "what we claim / what we do
not", and the right-hand column names the 20 percent reduction, the forecaster
quality, 500-robot operation, hardware validation, and novelty for N1/N2/N4/N6.

This is the same call made for X-05. A deck that claims only what it measured
survives a Q and A; a deck carrying the cherry-picked +57.9 percent seed ends at
the first judge who asks what the sample size was. Slide 21 pre-writes that
exact question and answers it with the real number.

## Files added or changed

| file | note |
|---|---|
| `docs/gen_master_spec_pptx.py` | new, ~640 lines, the deck generator |
| `SWARMOS_Master_Specification_SIH26123.pptx` | new, 24 slides |
| `tools/patch_masterspec_import.py` | new, tidied the import block |

## State at the end of this leg

* 570 tests green.
* C1 zero collisions: PASS across 18 paired runs.
* C2: measured at +2.3 percent, published as a miss.
* X-01, X-05, X-23/24/25 all complete with written records.
* Two decks in the repo: the team plan and the master specification.

## Next

The highest-value remaining item is the powered C2 measurement - 18000 ticks,
15 to 20 seeds, reported as a confidence interval rather than a point estimate.
It is a few CPU-minutes and it either clears the 20 percent bar or settles that
it does not. Everything needed to run it already exists in
`tools/verify_criteria.py`; only `TICKS` and `SEEDS` change.
