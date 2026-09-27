# ROBONEX / SWARMOS - Final UI/UX Transformation Checkpoint

Governing spec: `ROBONEX_SWARMOS_FINAL_UI_UX_MASTER_PROMPT.docx` (544 lines, 38 sections).
Governing rule: **CHANGE THE LANDING EXPERIENCE. ENHANCE THE WAREHOUSE VISUALIZATION. DO NOT BREAK THE EXISTING PRODUCT.**

Report structure is the 12-part output required by section 37.

An important limitation is stated up front, because section 33 demands exact results
and forbids fabricated output: **the tool shell used to build this is network-isolated
from the browser, so no rendered pixel was ever observed.** Every claim below is either
(a) machine-verified, with the command and its actual output, or (b) explicitly marked
`PENDING SCREENSHOT`. Nothing visual is asserted as PASS on the strength of the code alone.

---

## 1. BASELINE

Recorded before the first edit, per section 3.

| Item | Value |
|---|---|
| git tip | `e67c440` |
| working tree | clean except 2 untracked `.docx` |
| `tools/verify_ui_contract.py` | `All machine-checkable UI contracts hold.` |
| `pytest tests/ -q` | **575 passed** in 104.82 s |

---

## 2. LANDING PAGE (STATE 1)

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | `/` serves a ROBONEX landing page, not the dashboard | **PASS** | `GET / -> 200`, `ROBONEX in body: True`, `landing != dashboard: True` |
| 2 | `ROBONEX` wordmark top-left (section 6) | **PASS (markup)** / PENDING SCREENSHOT (placement) | `.lp-head__left > .lp-wordmark`, header is `justify-content: space-between` |
| 3 | `SIH / SMART INDIA HACKATHON` top-right, one line on desktop | **PASS (markup)** / PENDING SCREENSHOT | single `.lp-sih` span, `white-space: nowrap` |
| 4 | `SWARMOS` directly underneath the SIH text, not under ROBONEX | **PASS (markup)** / PENDING SCREENSHOT | both in `.lp-head__right`, `flex-direction: column; align-items: flex-end` |
| 5 | No SYSTEM / FLEET / SIMULATION / BENCHMARK nav links (sections 6, 31) | **PASS** | verifier: `no nav element (sections 6, 31)` |
| 6 | Hero title `ROBONEX` + `Distributed intelligence for autonomous warehouse fleets.` | **PASS** | verifier: `all 14 mandated strings present` |
| 7 | Robot centrepiece on a technical grid with a vignette (section 8) | **PASS (asset + CSS)** / PENDING SCREENSHOT | `web/assets/robot-hero.svg` XML-valid, `GET /assets/robot-hero.svg -> 200`, `.lp-grid` + `.lp-vignette` |
| 8 | Right card `SWARMOS` / `DECENTRALIZED MULTI-AMR COORDINATION` + all six capabilities | **PASS** | all six strings asserted by the verifier's `LANDING_COPY` table |
| 9 | Lower-left description + `AUTONOMOUS - DISTRIBUTED - RESILIENT - MULTI-AMR` | **PASS** | present in `web/landing.html` `.lp-about` |
| 10 | Status rows honest, no implied live telemetry (section 11) | **PASS** | verifier: `status degrades honestly when the server is silent`; unreachable renders `--` |
| 11 | `ENTER SWARMOS ->` enters the REAL simulation (section 12) | **PASS** | verifier: `ENTER SWARMOS starts the real run then opens the dashboard`; `POST /api/sim/start -> 200 True`, `running=True tick=1` |

All six advertised capabilities correspond to code that exists (M4 coordination, conflict
resolution, task allocation, spatio-temporal reservation, failure recovery, edge ML), so
the card is descriptive rather than aspirational.

---

## 3. LANDING -> SIMULATION TRANSITION

| Requirement | Result | Evidence |
|---|---|---|
| CTA starts a real run before navigating | **PASS** | `POST /api/sim/start -> 200 True`; status afterwards `running=True, tick=1` |
| Navigates to the existing dashboard, no fake sim | **PASS** | `DASHBOARD_URL = "index.html"`; `GET /index.html -> 200` with the real shell |
| Failure is reported, not hidden | **PASS (code path)** | non-ok response renders `COULD NOT START: <reason>`; unreachable renders `SERVER UNREACHABLE`; button re-enables |
| Transition restrained, 180 ms (section 13) | **PASS (CSS)** / PENDING SCREENSHOT | `.lp-transition` opacity 180 ms |
| `prefers-reduced-motion` respected | **PASS** | verifier: `landing.css honours prefers-reduced-motion`; JS skips the fade entirely |

---

## 4. SIMULATION, PANELS CLOSED (STATE 2)

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Shell boots with the panel closed (sections 15, 24) | **PASS** | verifier: `shell boots with the rail closed` |
| 2 | Rail element itself boots closed | **PASS** | verifier: `rail element boots closed` |
| 3 | Nothing opens the panel implicitly | **PASS** | verifier: `boot primes the default panel without revealing the rail` |
| 4 | A closed panel can be reopened at desktop width | **PASS** | verifier: `rail handle is available at every width` (was `display:none` above 1280 px before this work) |
| 5 | Warehouse floor / grid / racks / docks actually render | **PASS (data path)** / PENDING SCREENSHOT | defect N fixed; verifier: `all 6 warehouse keys map.js reads are produced by the normaliser` |
| 6 | Warehouse geometry is real, not decorative | **PASS** | live hello: `width=60 height=40 rack_spans=434`, docks 6 CHARGER / 9 PICK / 9 DROP |
| 7 | Dock types distinguishable without colour | **PASS (code)** / PENDING SCREENSHOT | CHARGER ring, PICK triangle, DROP square |
| 8 | Restricted / blocked region shown from real state | **PASS** | `blocked` now on the wire; proven `0 -> 23 -> 0` across a `BLOCK_AISLE` inject and clear |
| 9 | Paths legible with a five-level hierarchy | **PASS (code)** / PENDING SCREENSHOT | selected / conflict / moving / planned / secondary |
| 10 | Paths visible at the fitted zoom of a 60 m warehouse | **PASS** | the `s < LOD_PX_PER_M` early return that suppressed **all** paths below 6 px/m is removed; low zoom now simplifies instead of hiding |

---

## 5. SIMULATION, PANELS OPEN (STATE 3) - LOCKED

Sections 25 and 26 lock this state. It was not redesigned.

| # | Requirement | Result | Evidence |
|---|---|---|---|
| 1 | Panel architecture unchanged | **PASS** | five tabs, five panels, ids untouched in `index.html` |
| 2 | Tab labels unchanged | **PASS** | Fleet / Decision / Lab / Compare / Analytics |
| 3 | No panel markup rewritten | **PASS** | `git diff --stat`: `web/index.html` is **1 line** changed |
| 4 | Panel JS untouched | **PASS** | no file under `web/js/panels/` appears in the diff |
| 5 | Tab click still opens and renders the panel | **PASS** | `selectTab(name, reveal = true)`; every user-initiated call keeps the default |
| 6 | Arrow-key tab navigation intact | **PASS** | both arrow handlers call `selectTab` with the default `reveal` |
| 7 | Command-palette panel entries intact | **PASS** | the three palette actions call `selectTab` unchanged |
| 8 | Simulation logic untouched | **PASS** | no diff in `app/coordination/`, `app/ml/`, `app/sim/engine.py`, `robot.py`, `swarm_policy.py` |

---

## 6. EXISTING FUNCTIONALITY

| # | Capability | Result | Evidence |
|---|---|---|---|
| 1 | `GET /api/status` | **PASS** | `200`, `ok=True` |
| 2 | `POST /api/sim/start` | **PASS** | `200 True`, then `running=True tick=1` |
| 3 | `POST /api/sim/stop` | **PASS** | `200` |
| 4 | pause / resume / step | **PASS** | verifier: `start/step/pause/resume ok` for all 3 scenarios |
| 5 | `WS /ws/fleet` | **PASS** | hello received, `type=hello` |
| 6 | All 3 scenarios load | **PASS** | `blocked_aisle, narrow_aisle_deadlock, rush_50` |
| 7 | Fault injection | **PASS** | all 5 UI-exposed faults accepted |
| 8 | `/index.html` still the dashboard | **PASS** | `200`, `class="shell"` present |
| 9 | Static assets still served | **PASS** | `styles/landing.css`, `js/landing.js`, `assets/robot-hero.svg` all `200` |
| 10 | Determinism / `trace_hash` | **PASS** | `575 passed`, which includes the replay-hash suite |
| 11 | Safety invariants | **PASS** | `575 passed`, which includes the collision and arbiter suites |

---

## 7. AUTOMATED TESTS - ACTUAL OUTPUT

```
$ PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest tests/ -q
575 passed in 116.22s (0:01:56)
```

```
$ PYTHONPATH=. python3 tools/verify_ui_contract.py
34 pass, 1 warn, 0 FAIL
All machine-checkable UI contracts hold.
```

Baseline was `575 passed` and the verifier held. Test count is **identical**: no test was
added, removed, skipped, or weakened, and none broke. The single WARN is informational
(ids declared for CSS/aria that no JS reads, including the new `lp-title`, `lp-card-title`,
`lp-transition`), and it was already present at baseline.

In-process route regression via `starlette.testclient.TestClient`:

```
GET /           -> 200 | ROBONEX in body: True | landing.css: True
GET /index.html -> 200 | shell present: True | data-rail="closed": True
  landing != dashboard: True
GET /styles/landing.css        -> 200
GET /js/landing.js             -> 200
GET /assets/robot-hero.svg     -> 200
GET /api/status -> 200 True running= False
POST /api/sim/start -> 200 True
  after start: running= True tick= 1
WS /ws/fleet hello type= hello | warehouse keys: ['blocked', 'cell_m', 'chargers',
  'drop', 'height', 'pick', 'rack_spans', 'width', 'zones']
  width= 60 height= 40 rack_spans= 434 blocked= 0
POST /api/sim/stop -> 200
```

---

## 8. PROBLEMS FOUND

**Defect N - the warehouse static layer never rendered at all.** The single most
significant find. `web/js/store.js` assigned the WebSocket hello payload verbatim, while
`web/js/map.js` read four keys the payload never contained:

| `map.js` read | payload actually sent |
|---|---|
| `wh.width_m` -> `undefined` | `width: 60` (cells) |
| `wh.height_m` -> `undefined` | `height: 40` (cells) |
| `wh.racks` -> `undefined` | `rack_spans` (434 run-length `[x,y,run]`) |
| `wh.docks` -> `undefined` | `chargers` 6, `pick` 9, `drop` 9 |

So floor, grid, racks and docks drew nothing. Nothing in the repository emitted
`width_m` / `racks` / `docks`, and **zero tests asserted the render payload**, which is
why 575 green tests never noticed. This - not "low contrast" - was the true root cause
behind sections 16-22.

**Defect O - paths were suppressed entirely at the default zoom.** `drawPaths()` began
`if (s < LOD_PX_PER_M) { return; }`. A 60 m warehouse fits at roughly 0.57x, i.e. under
6 px/m, so the gate was always true and **no path ever drew**.

**Defect P - the desktop rail could not be closed.** `.rail-toggle { display: none; }`
with re-enablement only inside `@media (max-width: 1280px)`. Above 1280 px the panel was
permanently open, directly violating sections 15 and 24.

**Defect Q - boot opened the panel.** `selectTab("fleet")` runs once at startup and its
rail-opening side effect would have defeated the closed default.

**Defect R - the verifier only knew one HTML entry point.** `check_dom_ids()` read only
`index.html`, so every `#lp-*` id would have been reported missing once a second page
existed.

**Defect S - restricted region referenced data that was not on the wire.** I wrote the
cross-hatch against `wh.blocked` before the payload carried `blocked`; caught by
self-review, then wired through and proven with a real fault cycle.

**Defect T - the first hero SVG was not valid XML.** `xml.dom.minidom` rejected it:
XML forbids `--` inside a comment body, and the banner comments used dashed rules.

---

## 9. FIXES PERFORMED

1. **N** - added `normaliseWarehouse(wh)` in `store.js`, the one place the compact wire
   format becomes the renderer's metre vocabulary: cells -> metres, `rack_spans`
   expanded to 434 metre rects, `chargers`/`pick`/`drop` merged into one `docks` list
   tagged by kind, zones converted, malformed input -> `null`. Verified in node against
   the real payload: `width_m=60 height_m=40 racks=434 docks=24 {CHARGER:6,PICK:9,DROP:9}`.
   The backend keeps its compact format; the renderer keeps its own.
2. **O** - removed the early return; low zoom now *simplifies* (`PATH_DETAIL_PX_PER_M`)
   rather than hiding, and selected/conflict paths always draw.
3. **P** - `.rail-toggle { display: inline-flex; }` at every width, plus a
   `@media (min-width: 1281px)` rule where a closed rail returns its column width to the
   map instead of leaving a dead gutter. The sub-1280 px drawer rules were not touched.
4. **Q** - `selectTab(name, reveal = true)`; the boot call is `selectTab("fleet", false)`.
   Every user-initiated path keeps the default and still opens the panel.
5. **R** - `check_dom_ids()` now unions the ids of every `*.html` in `web/`.
6. **S** - `to_render_payload()` emits `blocked`; passed through in cell coordinates.
   Proven `0 -> 23 -> 0` across `block_aisle_segment(30,8,30)` and its clear.
7. **T** - replaced the dashed banners with short `<!-- torso -->` style comments and
   added a regex assertion that no comment body contains `--`. Re-validated: well-formed,
   14 paths, 6 circles, 3 ellipses, 6 gradients, 5479 bytes.
8. Sections 16-22 visual work: 11 new map tokens, typed dock glyphs (shape *and* colour,
   so it survives a poor projector), rack bay labels at high zoom, a cross-hatched
   restricted region, and the five-level path hierarchy with the unselected field subdued.
9. Three new verifier checks - `landing` (14 mandated strings, no commercial content, no
   nav, real CTA, honest degradation, reduced motion, no forked palette), `rail-default`
   (4 assertions), `render-payload` (the defect-N contract).

---

## 10. FILES MODIFIED

```
 app/api/server.py           |  31 +-   route "/" -> landing.html, FileResponse import, docstring
 app/sim/warehouse.py        |   5 +    emit "blocked" in to_render_payload (additive)
 tools/verify_ui_contract.py | 164 +    3 new checks, dual html entry points
 web/index.html              |   2 +-   ONE line: shell gains id + data-rail="closed"
 web/js/main.js              |  41 +-   rail toggle, selectTab reveal flag
 web/js/map.js               | 122 +    dock glyphs, path hierarchy, restricted region, LOD
 web/js/store.js             |  90 +    normaliseWarehouse
 web/styles/shell.css        |  21 +-   desktop-closable rail
 web/styles/tokens.css       |  20 +    11 new map tokens (additive)
```

New files:

```
 web/landing.html              86 lines
 web/styles/landing.css       411 lines
 web/js/landing.js            160 lines
 web/assets/robot-hero.svg   5479 bytes, XML-valid
 tools/patch_*.py             6 auditable patch scripts
 docs/ROBONEX_SWARMOS_UI_TRANSFORMATION_CHECKPOINT.md  (this file)
```

Total: **467 insertions, 29 deletions** across 9 tracked files. Section 32's minimum-diff
requirement is met: `web/index.html` changed by exactly one line, and no panel markup,
panel JS, coordination, ML, engine, robot or policy file was touched.

---

## 11. FILES INTENTIONALLY UNTOUCHED

Sections 1, 25 and 26 lock the product. Verified absent from `git diff --stat`:

- `app/coordination/` - **all** of it, including `swarm_policy.py` and `models.py`. The
  safety arbiter and every constant (`MAX_STEP_M`, `HARD_STOP_M`, `SOVEREIGN_MARGIN_M`,
  `CONFLICT_M`, `STALE_TICKS`) are byte-identical.
- `app/ml/` - all of it. The advisory-only fence (X-05) is unchanged.
- `app/sim/engine.py`, `app/sim/robot.py`, `app/sim/scenarios.py` - the authoritative
  state source and `COLLISION_DISTANCE_M` / `WAYPOINT_TOLERANCE_M` are unchanged.
- `app/db/` - all of it.
- `web/js/panels/` - every panel renderer.
- `web/js/transport.js`, `web/js/cosim.js`, `web/js/format.js`, `web/js/palette.js`.
- `web/styles/panels.css`.
- `tests/` - not one test was edited, so the 575 are the same 575.

`app/sim/warehouse.py` is the one simulation-side file in the diff. The change is five
lines that add an existing field to an outbound render payload; it reads state and
computes nothing, so no simulation behaviour can depend on it.

---

## 12. FINAL VERDICT

**LANDING + SIMULATION UI TRANSFORMATION COMPLETE - ALL SYSTEMS PASS**

Supported by: `575 passed` (identical to baseline), `34 pass, 1 warn, 0 FAIL` on the
extended contract verifier, and a live in-process exercise of `/`, `/index.html`, the
three static asset paths, `/api/status`, `/api/sim/start`, `/api/sim/stop` and
`/ws/fleet`.

**The verdict is qualified in exactly one way, and the qualification is deliberate.**
Per section 33 I must report the exact result and not fabricate output. Every *behavioural*
and *structural* requirement above is machine-verified. The requirements that are purely
about rendered pixels - header placement at desktop width, the robot's visual weight on
the grid, the perceived legibility of the five path levels, the dock glyph shapes, the
180 ms fade - are marked `PENDING SCREENSHOT` because the build shell cannot see the
canvas. They are implemented and their inputs are proven correct; they are not
*observed*. One screenshot of `/` and one of `/index.html` closes that gap.

### Known issue, deliberately not fixed here

A previously supplied screenshot showed every roster row at `0.00 m/s`, `TASKS PER MINUTE
0.03` at tick 163,011 with 291,938 replans - the fleet was gridlocked. That is a
coordination-behaviour problem inside the region sections 25 and 26 lock, so it was out of
scope for this task. It is worth noting that the path-legibility work above will make the
gridlock *more* visible, not less. This should be the next task.

Also still open from earlier work: criterion C2 (throughput gain) measured mean **-19.3
pct**, 95 pct CI [-36.0, -2.6] against a >= +20 pct target, published honestly in
`docs/SUCCESS_CRITERIA_VERIFICATION.md`. C1 (zero collisions) is met across 27 paired
9000-tick runs.
