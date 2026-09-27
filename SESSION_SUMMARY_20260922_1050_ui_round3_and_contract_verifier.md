# Session summary - UI defect round 3 and the UI contract verifier

Date: 2026-09-22
Commit: `3c02051` (parent `94af5f0`)
Gates: 575 pytest pass; `node --check` clean on all four edited JS files;
ASCII-only comments verified; `tools/verify_ui_contract.py` reports
`22 pass, 1 warn, 0 FAIL`.

## What triggered this round

The user ran `./run.sh --demo`, sent 8 screenshots, and reported four things
plus one request:

> Grid lines are not much visbile ... when i click fit/zoom out, dots appears
> very small ... Command wallet - if i press some keys ... nothing working ...
> in lab tab, when i changed scenario, nothing is happening even after pressing
> start/resume ... is there a way u only can run this and list out UI is
> responding as per your inputs? or guide me what all things i need to check

So the round had two halves: fix the defects, and remove my dependence on
screenshots by building something I can run myself.

## The five defects

### I - scenario dropdown sent `[object Object]`

`web/js/panels/lab.js:56` built the option as
`<option value="${s.id || s}">${s.name || s.id || s}</option>`.
`ScenarioSpec.as_dict()` (`app/sim/scenarios.py:130`) has no `id` field, so
`s.id || s` fell back to the whole record and stringified it. The *label* path
found `name`, so the dropdown rendered correctly - the bug was invisible until
Start returned:

```
Unknown scenario '[object Object]'. Choose one of: blocked_aisle, narrow_aisle_deadlock, rush_50.
```

Fixed to interpolate `s.name` for the value and `s.title || s.name` for the
label.

### J - grid lines nearly invisible

`web/styles/tokens.css` had `--map-grid: #161D25` and
`--map-grid-major: #1E2831` against `--map-floor: #0C1116` - only a handful of
RGB steps. Final values `#1B242C` / `#232D36`, measured contrast 1.206 and
1.355 against the floor, with major still darker than `--line-default`.

### K - robots collapsed to dots at Fit

`map.js` gated level of detail on `LOD_ZOOM = 0.6` compared against
`this.zoom`. But `zoom` is a *relative* multiplier: `scale() = fitScale * zoom`.
At Fit the readout was `ZOOM 0.58x`, below the threshold, so the fleet degraded
to bare dots despite having plenty of pixels. Replaced with six px-per-metre
constants - `LOD_PX_PER_M`, `LABEL_PX_PER_M`, `GRID_PX_PER_M`,
`GRID_MINOR_PX_PER_M`, `RACK_OUTLINE_PX_PER_M`, `DOCK_LABEL_PX_PER_M` - every
one compared against `s = this.scale()`.

### L - advertised keys did nothing

The palette showed `hint: "0"` and `hint: "Esc"`, and `transport.js:164` said
"press R to retry", but the only global listener was a bare Escape handler.
Added a real global `keydown` in `main.js` binding `0` to `map.fit()` and
`r`/`R` to `transport.retryNow()`, suppressed while a modifier is held, while
the focus is in an input/select/textarea/contenteditable, or while the palette
is open. Also removed `hint: "Lab"` - that is a destination, not a keystroke.

### M - stale-frame banner latched on forever

`_startStaleWatch()` raised the warn banner when frames were late, but cleared
it only under `age <= STALE_MS && store.link === LINK.DEGRADED`. `applyFrame()`
independently sets link back to LIVE as soon as a frame lands, so by the time
the watch ran the `DEGRADED` half was already false and the clear branch was
unreachable. Screenshots 5-8 show the banner sitting beside `LINK Live`. The
clear is now unconditional on link state and uses a `_staleBannerOn` ownership
flag so it cannot wipe a socket-closed or server-error banner.

## The three root-cause patterns

1. **A truthy-fallback chain that stringifies an object.** `a.x || a` fails
   *open*. Across a schema boundary, a `||` fallback must land on another
   field, never on the whole record.
2. **A threshold expressed in the wrong unit.** J and K are the same species: a
   value that governs pixel density was compared against a relative zoom
   multiplier.
3. **A state machine with an unreachable exit.** Raised on one condition,
   cleared on a condition that another code path invalidates first, therefore
   it latches.

Across all three rounds - A through M, thirteen defects - **every single one was
a contract that no test asserted.** Not one was a logic error inside a function
that unit tests cover. That is exactly the gap the user intuited.

## The verifier

`tools/verify_ui_contract.py`, about 430 lines, seven checks, exit 1 on any
FAIL, `--no-api` for a pure-static ~1 s run:

| check | asserts |
|---|---|
| `dom-ids` | every `$("x")` / `getElementById` / `querySelector("#x")` resolves to an id in `index.html` or minted by a JS template |
| `option-values` | the scenario `<option value>` interpolates a real field, not the record; every field used exists on every `list_scenarios()` row; every Lab fault id maps onto a `FaultKind` through `_FAULT_ALIASES` |
| `keyboard` | every key advertised in a palette `hint:` or a banner "press X to" string is bound in a real handler; the global handler has a text-entry guard |
| `tokens` | every `css("--x")` is declared; `--map-grid*` clears a WCAG-style relative-luminance floor against `--map-floor`; `--map-grid-major` stays below `--line-default` |
| `map-units` | no `*_PX_PER_M` compared against `this.zoom`, no `*_ZOOM` against `s`; bare literals in those gates flagged |
| `css-classes` | every class emitted from a JS template is targeted by a stylesheet |
| `api` | in-process `starlette.testclient.TestClient`: `/api/scenarios`, then stop/start/step/pause/resume for every scenario, then one inject per Lab fault |

Why static plus in-process rather than a live HTTP hit: my tool shell is
network-isolated from the user's browser. `curl 127.0.0.1:8770` returns nothing
from my side while their Chrome loads the page fine. I can never see rendered
pixels, so the verifier gets ground truth by parsing the JS, HTML and CSS,
cross-checking them against the Python API, and driving the real ASGI app in
process.

**The verifier earned its keep on its first run.** My round-3 token fix had
over-corrected `--map-grid-major` to `#2E3B47`, which is *brighter* than
`--line-default: #263039` - a direct violation of the "decoration stays quieter
than data ink" law. The contrast check caught it immediately and
`tools/patch_ui_round3b.py` brought it down to `#232D36`. A regression I
introduced myself, caught by a tool I had just written, inside the same round.

The single remaining WARN is documented and benign: a dozen `kpi-*` and `tab-*`
ids in `index.html` that JS reaches through computed selectors (`tab-${name}`,
`kpi-${key}`) which a regex cannot follow. Part 2 of the checklist exercises
all of them by hand.

## Process notes worth keeping

- Multi-file patch scripts must accumulate every edit into a `pending = {}`
  dict and write **all** files only at the very end. A script that saves as it
  goes leaves earlier files modified when a later assert aborts.
- The `sub()` assert-exactly-one-match helper has now caught real anchor
  ambiguity twice. Keep using it.
- Backups before each round: `/tmp/<name>.before_r3` for all five files.

## What is next

- Round 4 screenshot set to confirm I, J, K, L, M on the user's actual display.
  Only JS and CSS changed, so a hard reload (Ctrl+Shift+R) is enough - no server
  restart.
- The one genuine measurement gap is unchanged: **C2 is NOT met** on
  `avg_completion_s` (mean -19.3 pct, 95 pct CI [-36.0, -2.6], target >= 20
  pct), and that statistic is survivorship-biased across arms. Re-score on
  `tasks_per_min` or an equal-completion-count basis via
  `tools/verify_criteria_powered.py`, one unattended ~40 min run. C1 remains
  met: 0 collisions across 27 paired 9000-tick runs.
- Optional: wire `verify_ui_contract.py` into `run.sh --check`; raise task
  supply so `blocked_aisle` is not exhausted inside the run window.
