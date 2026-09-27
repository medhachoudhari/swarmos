# Session summary - UI defect round 2 (F, G, H)

Commit: `6ee6abc`  |  Gate: `575 passed in 94.56s`  |  Date: 2026-09-22 04:37 IST

## How these were found

The user launched `./run.sh --demo` and sent five browser screenshots of the
live app (Fleet at tick 456, the command palette open, Analytics at tick 1403,
Lab with `blocked_aisle`/fleet 24, and Lab showing the degraded banner). The
screenshots confirmed the round-1 fixes had landed - `VERDICTS 3,656` instead
of `NaN`, the Analytics legend no longer overlapping, the hero artwork
present - and exposed three further defects.

Screenshots remain the only channel that can see the rendered page: the tool
shell is network-isolated from the user's browser, so `curl 127.0.0.1:8770`
returns HTTP 000 while Chrome loads normally. This has now been proven twice.

## The three defects

### F - palette shortcut badges rendered as full-width bars

`.palette__item` was `display: grid; grid-template-columns: 1fr auto;` but
`palette.js` emits three children per row: name, description, and an optional
shortcut badge. Name took column one, description column two, and the badge
wrapped onto an implicit second row in the `1fr` column - so it painted as a
full-width bordered bar under the command name.

Fix: explicit `grid-template-areas: "name key" / "desc key"` with
`.palette__name { grid-area: name }`, `.palette__desc { grid-area: desc }` and
`.palette__key { grid-area: key; align-self: center }`. The name and
description now stack in column one and the badge sits in column two spanning
both rows.

Round 1 had given the badge its own `.palette__key` class. That was necessary
but insufficient: the badge was never the problem, the container was.

### G - the map state legend painted as a light grey panel

`main.js` renders each legend row as `<button class="legend__row" type="button">`
so a state can be muted from the keyboard, but `.legend__row` was styled as if
it were a `<div>` - only `display: flex` and spacing. Nothing reset the
user-agent `ButtonFace` background or the default border, so every row painted
light chrome over the translucent dark `.legend` panel.

Fix: an explicit reset (`appearance`, `-webkit-appearance`, `background: none`,
`border: 0`, `margin`, `padding`, `font: inherit`, `text-align: left`) ahead of
the existing flex layout.

### H - the map read as near-empty black space

`map.fit()` early-returns when `store.warehouse` is falsy. At boot it always
is: `store.js` initialises `warehouse = null` and only sets it from the first
websocket frame. `main.js` called `map.fit()` once during boot - a guaranteed
no-op - and nothing ever called it again, so `fitScale` was never derived from
the real warehouse. The zoom readout showed `1.00x` because `zoom` is a
separate multiplier from `fitScale`, which is why the symptom looked like an
empty canvas rather than a zoom problem.

Fix: `fit()` now sets a `_hasFit` flag, a new `maybeFitOnFirstWarehouse()`
returns early unless a warehouse is known and no fit has happened yet, and the
`requestAnimationFrame` loop in `start()` calls it every frame. It fits exactly
once, the first time a warehouse becomes known, and never again - refitting
later would yank the view out from under an operator who panned deliberately.

## Root-cause patterns worth remembering

Round 1 produced two patterns: one CSS class doing two unrelated jobs, and a
server/client key contract mismatch. Round 2 adds three more.

1. **A fix that treats the symptom rather than the layout container.** F was
   "fixed" in round 1 at the level of the badge. The grid was the defect.
2. **A semantic element styled as if it were a `<div>`.** G. When the markup is
   a `<button>`, `<input>` or `<select>`, the user-agent stylesheet wins unless
   it is explicitly reset.
3. **A lifecycle/ordering bug.** H. The call existed, was correct, and ran
   exactly once at the one moment its precondition was guaranteed false.

## Process notes

The `sub(text, old, new, label)` assert-exactly-one-match helper did its job:
it refused the H anchor `    if (this._staticDirty) this.drawStatic();` because
that line occurs in both `onFrame()` and the `start()` raf loop, failing with
`AssertionError: H frame hook: expected 1 match, found 2`. That forced a
deliberate read of the surrounding code and the correct choice - `onFrame()`
early-returns on a missing warehouse, so only the raf loop can ever trigger
the first fit. A blind `replace` would have patched the wrong site and left H
silently unfixed.

**New hazard recorded**: `tools/patch_ui_round2.py` saves each file as it
finishes it, so the abort left `panels.css` written (F and G applied) and
`map.js` untouched. The rerun required restoring `panels.css` from
`/tmp/panels.before_r2.css` first, otherwise the F/G `sub()` calls would have
asserted with `found 0`. Future multi-file patch scripts should either apply
every edit in memory and save all files at the end, or be written to be
idempotent.

## Verification

- `node --check web/js/map.js` - ok
- `panels.css` braces balanced 112/112, zero non-ASCII characters
- Patched regions read back with `grep -n`: `map.js:124-148` and `:637`,
  `panels.css:22-30` and `:478-482`
- `pytest tests/ -q` - 575 passed (no Python was touched, so unchanged)
- Backups: `/tmp/panels.before_r2.css`, `/tmp/map.before_r2.js`

## Still open

1. **Round-3 screenshot confirmation** of F, G and H: first load, Ctrl-K, and
   the map after Start. Only the browser can verify these.
2. **Re-score C2 on an unbiased statistic.** C2 is measured at mean -19.3 pct
   (95 pct CI [-36.0, -2.6]) against a >= 20 pct target and is published
   honestly as NOT MET. Two structural findings stand: task supply rather than
   run length is the binding constraint, and `avg_completion_s` is
   survivorship-biased across arms. Switching to `tasks_per_min` or an
   equal-completion-count comparison needs a patch to
   `tools/verify_criteria_powered.py` plus one unattended ~40 min run. This is
   the only genuine measurement gap left.
3. **Optional**: raise task supply so `blocked_aisle` is not exhausted inside
   the run window.
4. **User-side**: rehearse `docs/DEMO_RUN_ORDER.md` against a stopwatch.
