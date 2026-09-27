# SWARMOS UI verification

Two halves. Run the machine half first; it is free and it catches the whole
class of bug that has bitten us three rounds running. Then walk the human half,
which covers only what a browser can see and a script cannot.

---

## Part 1 - the machine half (run this every time)

```bash
cd /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920
PYTHONPATH=. /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
    tools/verify_ui_contract.py
```

Expected tail:

```
22 pass, 1 warn, 0 FAIL
All machine-checkable UI contracts hold.
```

Exit code 0 means every contract holds. Add `--no-api` to skip the in-process
server smoke and run purely static (about 1 s).

### What it actually asserts

| Check | Contract | The defect it would have caught |
|---|---|---|
| `dom-ids` | every `$("x")` / `getElementById` / `querySelector("#x")` resolves to an id declared in `index.html` or minted by a panel template | a panel wiring up a control that does not exist |
| `option-values` | the scenario `<option value>` interpolates a *field* of the record, and that field exists on every `list_scenarios()` row; every fault id maps onto a `FaultKind` | **I** - `s.id \|\| s` produced `value="[object Object]"`, so Start failed with `Unknown scenario` while the dropdown *looked* right |
| `keyboard` | every key advertised in a palette `hint:` or in a banner "press X to ..." string is bound in a real keydown handler, and the global handler guards text entry | **L** - `0` and `R` were advertised and bound nowhere |
| `tokens` | every `css("--x")` the canvas reads is declared in a stylesheet; `--map-grid*` clears a contrast floor against `--map-floor`; `--map-grid-major` stays quieter than `--line-default` | **J** - grid colours only a few RGB steps above the floor. It also caught my own over-correction in round 3b |
| `map-units` | no threshold named `*_PX_PER_M` is ever compared against `this.zoom`, and no `*_ZOOM` against px-per-metre; bare numeric literals in those gates are flagged | **K** - `LOD_ZOOM` compared against a relative multiplier when the thing it governs is pixel density |
| `css-classes` | every class emitted from a JS template string is targeted by some stylesheet | **F**, **G** - a class doing two jobs / a `<button>` the UA stylesheet won |
| `api` | `GET /api/scenarios`, then for every returned name a real `start` -> `step` -> `pause` -> `resume`, then one `inject` per fault the UI offers - all in process via `starlette.testclient` | **I** end to end, and round 1's `error` vs `detail` mismatch |

### The one expected WARN

```
dom-ids  declared in index.html, never read by JS: kpi-*, tab-*
```

Benign. Those ids are reached through computed selectors (`tab-${name}`,
`kpi-${key}`), which a regex cannot follow. Everything in the list is exercised
by Part 2 step 2 and step 5.

### Why a script and not a browser

My tool shell is network-isolated from your browser - `curl 127.0.0.1:8770`
returns nothing from my side while your Chrome loads the page fine. So I cannot
see rendered pixels, ever. The verifier is how I get ground truth without them:
it parses the JS, HTML, CSS and the Python API and cross-checks the contracts
between them, and it drives the real ASGI app in process. That covers wiring
completely. It cannot cover appearance, which is Part 2.

---

## Part 2 - the human half (about 4 minutes)

Start fresh so nothing is cached:

```bash
cd /home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920
./run.sh --demo
```

Then in the browser do a hard reload (Ctrl+Shift+R). **CSS and JS edits need
that reload; Python edits need the server restarted.**

### 1. Map, at first paint
- [ ] The warehouse is visible immediately - floor, racks, docks, robots. Not an
      empty black rectangle.
- [ ] Grid lines are legible: a fine 1 m grid plus a stronger line every 5 m.
- [ ] The grid is clearly quieter than the robots and the panel edges. If the
      grid is the first thing your eye lands on, it is too bright - say so.
- [ ] Topbar reads `LINK Live` and the tick counter is climbing.

### 2. Map, zoom and Fit
- [ ] Scroll to zoom in. Robots grow, get a heading wedge and a footprint ring,
      and ids appear once they are big enough to read.
- [ ] Press `0` (or the Fit control). The whole warehouse frames itself.
- [ ] **At Fit the robots must still be shaped robots, not 2 px dots.** This is
      defect K. If they collapse, screenshot it with the `ZOOM` readout visible.
- [ ] Zoom far out past Fit. Only *then* should they simplify to dots, and the
      minor grid should drop before the major grid does.

### 3. Command palette
- [ ] `Ctrl+K` opens it. The input is focused, the list is filtered as you type.
- [ ] Arrow Up / Arrow Down move the selection, `Enter` runs it, `Esc` closes.
- [ ] Every row that shows a key badge - `0`, `Esc` - must actually work with
      the palette closed. `0` fits the map. `Esc` clears the robot selection.
- [ ] "Start run" has no key badge any more. That is intentional: it used to say
      `Lab`, which is a destination, not a keystroke.
- [ ] Type in the Lab seed or fleet field and press `0`. **The map must not
      jump** - single-letter shortcuts are suppressed while you are typing.

### 4. Lab tab - the full loop
- [ ] Change the scenario dropdown to `narrow_aisle_deadlock`. Press **Start**.
- [ ] The map must rebuild with the new warehouse and the new fleet size, and no
      error banner. This is defect I. If you see
      `Unknown scenario '[object Object]'`, screenshot it.
- [ ] Repeat for `blocked_aisle` and back to `rush_50`.
- [ ] Pause, then Step once. The tick counter advances by exactly 1.
- [ ] Resume. The 10 Hz flow returns.
- [ ] Pick each fault in turn and press Inject. Each must produce a visible
      consequence: a red FAILED robot, a purple QUARANTINED robot, a new
      obstacle, a teal SOVEREIGN robot on comm blackout.
- [ ] Stop. The fleet is released and the empty state names the next action.

### 5. Banners and the link state
- [ ] Pause the run for 2 s. A warn banner appears saying no frame for N ms, and
      `LINK` goes `Degraded`.
- [ ] Resume. **The banner must disappear and `LINK` must return to `Live`
      together.** This is defect M - the banner used to latch on forever while
      the topbar already read `Live`. If you see a stale-frame banner sitting
      next to `LINK Live`, screenshot both in one frame.
- [ ] Stop the server (Ctrl+C in the terminal). The banner turns to an error and
      offers a retry. Press `R`. It reconnects once the server is back.

### 6. No fake data
- [ ] Before any run, every KPI reads `--`, never `0` and never a placeholder.
- [ ] Select a robot with nothing assigned. Empty fields read `--`.

### 7. Right rail and bottom strip
- [ ] All five tabs open: Fleet, Lab, Inspector, Analytics, Co-sim.
- [ ] Legend rows toggle their status on and off, and the counts track the map.
- [ ] Every legend colour actually appears on a robot at some point in a run.

---

## What to send me when something is wrong

One screenshot with the offending thing **and** the topbar in the same frame
(so I can see LINK, tick and zoom), plus the browser console if it logged
anything. That is the only channel through which I can see rendered output, so
the more state that is in the frame, the fewer rounds we need.

Before you send it, run Part 1. If it already reports a FAIL, that is the bug,
and I can fix it without a screenshot at all.
