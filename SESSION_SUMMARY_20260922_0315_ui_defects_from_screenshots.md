# Session Summary - 2026-09-22 03:15 - Five UI defects fixed from live screenshots

## What triggered this leg

The user asked three things at once: whether the coding was finished, what
screenshots to share, and whether robot artwork could be added to the page
"to give impression that its a robot related... still all the fonts/dots should
appear."

They then captured and sent **12 full-window screenshots of the running app**.
That turned the task from "add an image" into "add the image and fix the five
real defects the screenshots just exposed." This is the first time the UI had
ever been seen rendered: my shell is network-isolated from the user's browser
(`curl http://127.0.0.1:8770` returns HTTP 000 while Chrome loads the page
fine), so no amount of local verification could have caught these.

## The five defects, and the two patterns behind them

Four of the five reduce to two root-cause patterns worth remembering.

### Pattern 1 - one CSS class doing two unrelated jobs

**Defect B - palette shortcut badges rendered as full-width bars.**
`.palette__hint` in `web/styles/panels.css` styled the footer hint bar
(`display:flex`, `border-top`, padding) while `web/js/palette.js` applied the
same class to each row's shortcut badge. One class cannot be both a full-width
bordered bar and an inline badge. Fix: a dedicated `.palette__key` for the badge,
plus a comment on `.palette__hint` recording the split so nobody re-merges them.

**Defect C - the "100 ms tick budget" legend spilled across the chart.**
`.chart__key` was `display:inline-block; width:8px; height:2px`, but
`analytics.js` uses it as the *legend text wrapper* with an `<i>` swatch inside.
The wrapper was therefore forced to 8x2 px and overflowed. Fix: `.chart__key`
becomes an `inline-flex` wrapper, `.chart__key > i` is the 8x2 swatch, and
`.chart__legend` may wrap.

### Pattern 2 - a server/client key contract mismatch

**Defect D - every 4xx in the product showed a bare "HTTP 400".** This was the
most serious finding of the session. `app/api/server.py:87`:

```python
def _fail(message, status=400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)
```

The human sentence lives under `"error"`. But both error sites in
`web/js/transport.js` read `data.detail`. `grep -rn '"detail"' app/` proved the
API error surface never sends `detail` at all. So **every failed request
anywhere in the product silently discarded its explanation** - exactly what the
screenshots showed in the Lab panel. Fix: an `apiError(data, status)` helper that
prefers `error`, falls back to `detail` (because `app/api/runner.py:302` does
return `detail` on a *success* path), then to a plain sentence.

Diagnostic note: I first suspected a run-state-machine rejection and wrote
`tools/diag_lab_start_400.py`, an in-process `starlette.testclient.TestClient`
probe that started a run, started a second over it, stepped, stopped and
restarted. All five returned 200, which ruled out the state machine and pointed
straight at the key mismatch. Worth keeping as a technique: `TestClient` against
the real `app` object works even with no network.

### The remaining two

**Defect A - the bottom strip read "VERDICTS NaN" for an entire run.**
`engine.py:1327` emits `"verdicts": dict(self.verdict_counts)` - a nested map of
kind to count - and `main.js` passed it to `int()`, so `Math.round({})` is `NaN`.
Fix: `verdictTotal()` sums the counts and still returns `DASH` when there is no
data, so a missing value is never drawn as a zero (the no-fake-data rule).

**Defect E - no robotics identity on the landing screen.** Addressed with
hand-authored inline SVG, because this machine has no network access and no
raster asset can ever be fetched; vector also stays crisp on a projector. Two
additions to `web/index.html`: a 24x24 `.brand__glyph` beside the wordmark, and a
192x192 warehouse AMR hero inside `#map-placeholder` containing a faint floor
grid, the dashed `R_comm = 15 m` ring, a slowly rotating sensing arc, a load deck
with a payload tote, a lidar puck in the single saturated accent
(`--state-sovereign`), wheels, and peer dots at the map's own 4 px LOD size.

Two deliberate design decisions here:

1. **A mobile base, not a humanoid.** The reference image the user sent was a
   consumer humanoid robot. Drawing a humanoid would invite a bad Q&A question,
   because the simulation models warehouse mobile bases. The art now matches what
   the system actually is.
2. **The user's constraint "still all the fonts/dots should appear" is satisfied
   structurally, not by care.** The hero lives only inside `#map-placeholder`,
   which `index.html` hides the moment the first state frame arrives, and the
   whole `.hero` subtree is `pointer-events: none`. It therefore *cannot* cover a
   live robot dot or a metric. It also hides below 1100 px width and its
   animation is disabled under `prefers-reduced-motion`.

## How the change was made

All five fixes plus the artwork were applied in **one gated transaction**,
`tools/patch_ui_from_screenshots.py`, using the assert-exactly-one-match helper
so a silent partial patch is impossible (the defect D block asserts exactly two
matches, since both error sites were identical). Backups first to
`/tmp/*.before_ui_fixes.*`.

Gates, all green:

- `node --check` on `main.js`, `transport.js`, `palette.js`
- ascii-only check: `web/index.html` 11762 bytes non-ascii=0; `panels.css` 16500
  bytes non-ascii=0
- `<div>` open/close balance in `index.html`: 35 / 35
- patched regions read back with `sed -n` / `grep -n` (no syntax checker exists
  for HTML or CSS) - confirmed no id or class consumed by `web/js` was renamed
- full suite: **575 passed in 91.15s**, unchanged, as expected since no Python
  behaviour was touched

Commit: **09074bc** "UI: fix five defects found in live browser screenshots; add
robot artwork" - 7 files, 497 insertions, 6 deletions. Previous tip was aa8c7f4.

## Demo artefacts written this leg

- **`docs/DEMO_RUN_ORDER.md`** (161 lines) - a six-beat, five-minute run order
  with a time budget, one sentence to say and one exact click per beat; a
  five-item pre-flight checklist; a recovery table; and four things never to do
  on stage. Beat 4 leads with adversarial containment because that is the most
  BEL-relevant capability. Beat 5 states the C2 shortfall out loud.
- **`docs/JUDGE_QA_SHEET.md`** (165 lines) - 15 questions in three tiers with
  short answers, a table of the nine measured numbers and the file each lives in,
  and three sentences never to say. Governing rule: never invent a number, never
  oversell the ML as a safety feature.

The C2 shortfall is presented as a strength in both documents. The honest version
("we measured minus 19 percent, here is the measurement bug that caused it, here
is the fix") scores better with a technical panel than a round claimed win with
n=1, and it is the only version consistent with what the repository contains.

## What remains

1. **Fresh screenshots** to confirm the five fixes visually: first load (hero art
   + `VERDICTS --`), Ctrl-K palette (badges hug their text), Analytics tab
   (legend no longer overlaps the chart), Lab tab with a bad config (a human
   sentence instead of "HTTP 400").
2. **Re-score C2 on an unbiased statistic** - `tasks_per_min`, or matched
   completion counts. Needs a patch to `tools/verify_criteria_powered.py` plus one
   ~40 minute run.
3. **Optionally raise task supply** so `blocked_aisle` is not exhausted inside the
   run window. Already proven: at 9000 ticks the baseline trace is byte-identical
   to 1800, so longer runs cannot power C2 - task supply is the binding
   constraint.
4. **Rehearse** the run order against a stopwatch. The document is written; it has
   not been performed.

## Reusable notes for the next session

- The 12 screenshots caught five defects in one pass that local tooling could not
  see at all. **Ask for screenshots early and often** on any UI work here.
- `starlette.testclient.TestClient` against the real `app` object is the way to
  interrogate HTTP behaviour with no network.
- `grep -rn '"key"' app/` is a cheap, decisive way to prove a key is absent from
  an entire package - that is what settled defect D.
- Two defects came from CSS class reuse and one from a key-name mismatch. Both are
  the same underlying failure: an implicit contract with no single owner. Worth a
  sweep for other reused class names and other client-side reads of server keys.
