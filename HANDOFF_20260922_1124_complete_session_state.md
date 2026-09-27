# SWARMOS - COMPLETE SESSION HANDOFF

**Read this file first.** It is the single self-contained brief needed to resume
work on this project from any ACC terminal with no prior conversation context.

- Written: 2026-09-22 11:24 IST
- Repo: `https://github.com/adithyad-cs/swarmos-member4-coordination.git`
- Local path on the original machine: `/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920`
- HEAD at handoff: `69709c7` ("docs: session summary for UI round 3 and the contract verifier")
- Test gate at handoff: **575 pytest pass**
- UI contract verifier at handoff: **22 pass, 1 warn, 0 FAIL**

---

## 0. How to resume on a new ACC terminal - do this in order

```bash
# 1. Get the code
git clone https://github.com/adithyad-cs/swarmos-member4-coordination.git swarmos
cd swarmos
git log --oneline -5          # top commit should be 69709c7 or later

# 2. Confirm the Python interpreter. THIS MATTERS - see section 2.
/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -V   # must say 3.12.x
python3 -V                                                          # may say 3.4.1 - do NOT use

# 3. Run the test gate
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
  /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -m pytest tests/ -q
# expect: 575 passed

# 4. Run the UI contract verifier
PYTHONPATH=. /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
  tools/verify_ui_contract.py
# expect: 22 pass, 1 warn, 0 FAIL

# 5. Launch the demo
./run.sh --demo          # then open http://127.0.0.1:8770
```

If step 3 or 4 does not produce those numbers, **stop and diagnose before
changing anything** - those two numbers are the baseline every future change is
measured against.

Then read, in this order: this file, `docs/UI_VERIFICATION_CHECKLIST.md`,
`docs/SUCCESS_CRITERIA_VERIFICATION.md`, `docs/DEMO_RUN_ORDER.md`,
`docs/JUDGE_QA_SHEET.md`, and the session summaries in date order.

---

## 1. What the project is

**SWARMOS - Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile
Robots (AMRs) in Smart Warehouses.**

- Smart India Hackathon problem ID **SIH26123**
- Sponsor: **Bharat Electronics Limited (BEL)**
- Theme: Robotics & Drones
- Team of 5 students, software only
- Judged on a short live demo plus Q&A

The deliverable is a browser dashboard over a live 10 Hz warehouse simulation,
with a distributed coordination layer that provably prevents collisions and
contains an adversarial ("rogue") robot. Everything runs locally - no cloud, no
network, no pip installs.

### The six modules (all implemented in this repo)

| Module | Area | Location |
|---|---|---|
| M1 | Frontend dashboard | `web/` |
| M2 | Backend API and WebSocket | `app/api/` |
| M3 | AI/ML advisory layer | `app/ml/` |
| M4 | Robotics coordination / safety arbiter | `app/coordination/` |
| M5 | Simulation engine | `app/sim/` |
| M6 | Database and analytics | `app/db/` |

Roughly 24,000+ lines of code. **All six modules were implemented in this ACC
session**, not split across the team - the owner asked for that explicitly.

---

## 2. Environment facts - the hard-won ones

These are all verified on the original machine. Re-verify on the new terminal.

### Python
- **Use `/pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3`.**
  The default `python3` on PATH may be 3.4.1, which cannot parse this codebase.
- **`fastapi` 0.104.1 and `starlette` 1.6.0 are mutually incompatible on this
  machine - FastAPI is unusable.** The API is written directly against **raw
  Starlette**. Do not "helpfully" reintroduce FastAPI.
- Available: `uvicorn`, `websockets`, `pydantic`, `numpy`, `pandas`,
  `scikit-learn`, `python-pptx`, `pytest` 9.1.1, `sqlite3`.
- **`scipy` is NOT guaranteed.** Anything needing a t-distribution uses a
  hard-coded critical-value table (see `tools/verify_criteria_powered.py`).
- **NO NETWORK, NO PIP.** All robot artwork is hand-authored inline SVG for this
  reason. Never add a dependency.

### The pytest invocation
A stale site-wide plugin breaks plain `pytest`. Always use:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. \
  /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 -m pytest tests/ -q
```
Full run takes about 95-115 s.

### Shell and tooling quirks on an ACC terminal
- Every command emits two `[INFO] set $FDIPGLOB` lines. Filter with
  `| grep -v '^\[INFO\]'`.
- Commands time out at **300 s** and then continue in the background. Wrap long
  runs in `timeout 280`.
- Repeating an identical command three times trips a "not making progress"
  rejection. Vary the command text.
- **`node` IS available** and is used as the JS syntax gate: `node --check f.js`.
- **`read_file` on a large file with a relative path can silently return a
  3-line stub.** Read large files with `sed -n 'A,Bp' path` through the shell.
- `write_to_file` was denied in this session. **The proven workaround is a shell
  heredoc**: `cat > path/file.py <<'PYEOF' ... PYEOF` (use `<<'MDEOF'` for
  markdown). Every file in this repo was written that way.
- **NEVER run `pkill -f 'uvicorn app.api.server'` - it kills the agent's own
  shell.** Stop the server with Ctrl+C in its own terminal.

### The isolation that shapes everything
**The agent's tool shell is network-isolated from the user's browser.**
`curl http://127.0.0.1:8770/` returns nothing from the agent side while the
user's Chrome loads the page perfectly. Consequences:
1. The agent can never see rendered pixels. UI bugs are found only from
   screenshots the user sends, or from static analysis.
2. Any API verification must be **in-process**, via
   `starlette.testclient.TestClient(app)`, never a live HTTP request.
   `tools/verify_ui_contract.py` is built on exactly that constraint.

### Editing discipline used throughout (keep it)
Inline edits are made by writing a `tools/patch_*.py` script via heredoc and
running it, using this guard:
```python
def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)
```
This assert-exactly-one-match helper has caught real anchor ambiguity twice.

**HAZARD, learned the hard way:** a multi-file patch script that saves each file
as it finishes leaves earlier files modified when a later assert aborts.
**Accumulate every edit into a `pending = {}` dict and write all files only at
the very end.** `tools/patch_ui_round3.py` is the reference implementation.

Gates after any edit: `.py` -> `ast.parse`; `.js` -> `node --check`;
`.sh` -> `bash -n`; `.css`/`.html` -> no gate, read back with `sed -n`/`grep -n`.

### ASCII-only rule for code comments
No emoji, smart quotes, arrows, em-dashes or box-drawing inside Python, JS or
CSS comments. Use `-`, `'`, `"`, `...`. Verify with
`grep -nP '[^\x00-\x7F]' <file>`. (Markdown and chat are exempt.)

---

## 3. Architecture - the four laws

These are non-negotiable. Several past defects came from violating them.

- **L1 - M5 simulation is the single authoritative source of robot state.**
  Nothing else may mutate position, heading or battery.
- **L2 - M4 coordination is the binding safety arbiter.** Its veto is final.
- **L3 - M3 ML is ADVISORY ONLY and is never in the safety path.** This is
  structurally fenced and tested (`tests/test_ml_fence.py`). See
  `docs/X05_FORECASTER_DECISION.md`.
- **L4 - ONE canonical model per concept**, defined in
  `app/coordination/models.py`. No parallel shadow structs.

### Frozen conventions
- Continuous 2-D metres; heading in radians `[0, 2pi)`; battery `0-100`%.
- **Tick rate 10 Hz, so a 100 ms compute budget per tick.**
- Robot ids `R###`, task ids `T###`.
- Comms radius `R_comm = 15 m`; heartbeat 10 Hz; suspicion 200 ms;
  confirmation 500 ms.
- Aisle pitch 1.0 m; robot radius 0.35 m.

### Safety constants and where they live
| Constant | Value | File:line |
|---|---|---|
| `COLLISION_DISTANCE_M` | 0.70 | `app/sim/engine.py:62` |
| `WAYPOINT_TOLERANCE_M` | 0.08 | `app/sim/robot.py:47` |
| `MAX_STEP_M` | 0.22 | `app/coordination/swarm_policy.py:90` |
| `HARD_STOP_M` | 0.75 | `app/coordination/swarm_policy.py:134` |
| `SOVEREIGN_MARGIN_M` | 0.35 | `app/coordination/swarm_policy.py:150` |
| `CONFLICT_M` | 0.97 | `app/coordination/swarm_policy.py:161` |
| `STALE_TICKS` | 3 | `app/coordination/swarm_policy.py:240` |
| `MONITOR_SCALES` | (1.0, 0.75, 0.5, 0.25) | `app/coordination/swarm_policy.py:346` |

### API and engine facts that bite
- `SimEngine.__init__(self, scenario=DEFAULT_SCENARIO, *, seed=42, policy=None, label="swarmos")`
  - **there is NO `fleet_size` keyword.** To change fleet size use
  `dataclasses.replace(scen, fleet_size=n)`.
- `SimRobot.position` is a plain `(x, y)` **tuple**. It has `velocity`, **not**
  `speed`.
- `/api/status` carries **no** `robots`, `kpis` or `events`. Those exist only on
  the WebSocket `/ws/fleet`.
- `sim_inject` reads the key **`fault`**, not `kind`.
- `FaultKind` values are UPPERCASE, 10 total: `ROBOT_FAILURE`, `BATTERY_DRAIN`,
  `BLOCK_AISLE`, `CLEAR_BLOCKAGE`, `ROGUE_ROBOT`, `LINK_IMPAIR`,
  `ZONE_PARTITION`, `TASK_BURST`, `KILL_ML`, `COMM_BLACKOUT`.
  `app/api/runner.py:288 async def inject(self, fault, **params)` maps lower-case
  UI ids through `_FAULT_ALIASES`. The Lab UI exposes 5 of the 10:
  `robot_failure`, `comm_blackout`, `link_impair`, `blocked_aisle`,
  `rogue_agent`.
- **Scenarios** (`app/sim/scenarios.py`): `rush_50` (fleet 50),
  `narrow_aisle_deadlock` (24), `blocked_aisle` (40).
  `list_scenarios()` at `:238` returns `[SCENARIOS[n].as_dict() for n in sorted(SCENARIOS)]`
  and `ScenarioSpec.as_dict()` at `:130` returns `{"name": ..., "title": ..., ...}`
  - **there is NO `id` key.** That absence caused defect I.

---

## 4. UI/UX design laws

The owner's standing instruction: *"Give more focus on building best UIUX and
Simulation as judges will pay more attention on this part. And it should not at
all look like vibe coded web site."* Stack is **Vanilla JS + Canvas**, no
framework.

- **Three-level ink.** Primary `#E8EDF2`, secondary `#9AA7B4`, tertiary
  `#63707D`, on surface `#0F1419`.
- **Saturated colour encodes STATE only** - never decoration:
  BLOCKED `#E5484D`, WAITING `#F5A623`, CHARGING `#3E9BFF`, MOVING `#C8D2DC`,
  AVAILABLE `#2F6F4E`, FAILED `#6E3A3C`, QUARANTINED `#A855C4`,
  SOVEREIGN `#4FB3A6`.
- **NO FAKE DATA, EVER.** A missing value renders `--` via the exported `DASH`
  in `web/js/format.js`. Never `0`, never a placeholder.
- Motion only 120-200 ms. Keyboard-first.
- Fixed shell: **68% map / 22% right rail / 10% bottom strip.**
- **Map decoration must stay quieter than data ink.** The verifier now enforces
  this numerically on the grid tokens.

---

## 5. Where the project stands

### Done
- All six modules implemented and integrated.
- 575 tests passing.
- X-01 sovereign mode: **complete**.
- X-05 forecaster: **decided and fenced** (`docs/X05_FORECASTER_DECISION.md`).
- X-12 / N10 counterfactual co-simulation: implemented
  (`tests/test_cosim.py`, `tests/test_cosim_api.py`).
- 25-slide master spec deck: `SWARMOS_Master_Specification_SIH26123.pptx`.
- Demo run order, judge Q&A sheet, integration contracts: all in `docs/`.
- Three rounds of UI defect fixes (A through M, thirteen defects).
- Headless UI contract verifier plus a manual browser checklist.

### Novelty register (what to emphasise to judges)
- **N3** deterministic replay via `trace_hash`
- **N5** Simplex runtime assurance
- **N9** adversarial robot containment - **the most BEL-relevant item**
- **N10** counterfactual co-simulation (= X-12)

### Measured success criteria - report these honestly
- **C1 MET.** Zero collisions across 27 paired 9000-tick runs. Caveat stated in
  the docs: the baseline also scored zero, so C1 is *necessary but not
  differentiating*.
- **C2 NOT MET.** Mean **-19.3 pct**, 95 pct CI **[-36.0, -2.6]**, target
  **>= 20 pct**. Published as-is in `docs/SUCCESS_CRITERIA_VERIFICATION.md` and
  on slide 18 of the deck. **Do not quietly dress this up** - the honesty is
  itself defensible, and two structural findings explain it:
  1. Task supply, not run length, is the binding constraint.
  2. `avg_completion_s` is survivorship-biased across arms.

---

## 6. UI defect history - thirteen defects, one lesson

Full write-ups in `SESSION_SUMMARY_20260922_0315_*`, `..._0437_*` and
`..._1050_*`. The pattern matters more than the individual bugs.

**Round 1 (A-E)** and **round 2 (F, G, H)** root causes: one CSS class doing two
jobs; a server/client key mismatch (`error` vs `detail`); a fix that treated the
symptom rather than the layout container; a semantic `<button>` styled as a
`<div>` so the user-agent stylesheet won; a lifecycle bug where `fit()` ran at
the one moment its precondition was guaranteed false.

**Round 3 (I, J, K, L, M)** - the most instructive:

| # | Symptom | Root cause |
|---|---|---|
| I | Lab scenario change did nothing; `Unknown scenario '[object Object]'` | `<option value="${s.id \|\| s}">` - no `id` field exists, so the fallback landed on the whole record. The *label* path found `name`, so it looked correct while the value was broken |
| J | Grid lines invisible | `--map-grid` only a few RGB steps above `--map-floor` |
| K | Robots collapsed to dots at Fit | `LOD_ZOOM` compared against `this.zoom`, a *relative* multiplier on `fitScale`, while the thing it governs is *absolute* pixel density |
| L | Advertised keys `0` and `R` did nothing | Only `Escape` was ever bound |
| M | Warn banner latched on beside `LINK Live` | The clear branch was gated on `link === DEGRADED`, but `applyFrame()` sets link back to LIVE first, so the exit was unreachable |

### The three transferable root-cause patterns
1. **A truthy-fallback chain that stringifies an object.** `a.x || a` fails
   *open*. Across a schema boundary a `||` fallback must land on another
   **field**, never on the whole record.
2. **A threshold expressed in the wrong unit.** J and K are the same species -
   a value governing pixel density compared against a relative zoom multiplier.
3. **A state machine with an unreachable exit.** Raised on one condition,
   cleared on a condition another code path invalidates first, therefore it
   latches forever.

### THE headline finding
**All thirteen defects were contracts that no test asserted.** Not one was a
logic error inside a function that unit tests already covered. 575 passing tests
did not catch a single one of them. That is why the verifier exists.

---

## 7. The UI contract verifier - the key new asset

`tools/verify_ui_contract.py`, about 430 lines. Exits 1 on any FAIL.
`--no-api` gives a pure-static run in about 1 s.

```bash
PYTHONPATH=. /pkg/OSS-python-/3.12.0/x86_64-linux4.18-glibc2.28/bin/python3 \
  tools/verify_ui_contract.py
```

| Check | What it asserts |
|---|---|
| `dom-ids` | every `$("x")` / `getElementById` / `querySelector("#x")` in `web/js/**` resolves to an id in `web/index.html` or one minted inside a JS template |
| `option-values` | the scenario `<option value>` interpolates a real **field**, not the record (FAILS on the `\|\| s` signature); that field exists on every `list_scenarios()` row; every Lab fault id maps onto a `FaultKind` via `_FAULT_ALIASES` |
| `keyboard` | every key advertised in a palette `hint:` or a banner "press X to" string is bound in a real keydown handler; the global handler has a text-entry guard |
| `tokens` | every `css("--x")` the canvas reads is declared in `web/styles/*.css`; `--map-grid` and `--map-grid-major` clear relative-luminance contrast floors (1.12 / 1.25) against `--map-floor`; `--map-grid-major` stays darker than `--line-default` |
| `map-units` | no `*_PX_PER_M` is ever compared against `this.zoom`, and no `*_ZOOM` against `s`; bare numeric literals in those gates are flagged |
| `css-classes` | every class emitted from a JS template string or `index.html` is targeted by some stylesheet (WARN level) |
| `api` | via in-process `TestClient`: `GET /api/scenarios`, then `stop -> start -> step -> pause -> resume -> pause` for **every** scenario, then one `/api/sim/inject` per Lab fault against a live run. Treats both non-200 and `{"ok": false}` as failure |

**Current output: `22 pass, 1 warn, 0 FAIL`.**

The single WARN is benign and documented: a dozen `kpi-*` and `tab-*` ids
declared in `index.html` that JS reaches through computed selectors
(`tab-${name}`, `kpi-${key}`), which a regex cannot follow. Part 2 of the
checklist exercises all of them by hand.

**The verifier proved itself on its very first run.** The round-3 token fix had
over-corrected `--map-grid-major` to `#2E3B47`, which is *brighter* than
`--line-default: #263039` - a direct violation of the "decoration stays quieter
than data ink" law. The contrast check caught it immediately, and
`tools/patch_ui_round3b.py` brought it down to `#232D36`. A regression
introduced and caught inside the same round, by a tool written minutes earlier.

**Companion doc: `docs/UI_VERIFICATION_CHECKLIST.md`** - Part 1 is the machine
half (the command above, expected output, what each check asserts, which
lettered defect it would have caught, why a script and not a browser); Part 2 is
a 7-section manual browser checklist (map first paint; zoom and Fit; command
palette; the full Lab loop; banners and link state; no-fake-data; right rail and
bottom strip).

### The rule going forward
**Any new UI contract gets a check in the verifier, not just a code fix.** Three
rounds of screenshot ping-pong is the cost of not having done that earlier.

---

## 8. Running it

```bash
cd <repo>
./run.sh --demo            # then open http://127.0.0.1:8770
```

Modes: bare, `--open [PORT]`, `--demo [PORT]`, `--test`, `--check`.
Demo defaults: `DEMO_SCENARIO="rush_50"`, `DEMO_SEED=11`, `DEMO_FLEET=8`.

**Reload discipline:** CSS and JS edits need only a browser hard reload
(Ctrl+Shift+R). Python edits need the server restarted.

---

## 9. Open work, in priority order

1. **Round-4 visual confirmation of defects I-M.** Hard-reload the page and
   capture: the Lab tab with a changed scenario after pressing Start (I); the map
   at Fit with the `ZOOM` readout visible (J and K); `Ctrl+K` then `0` and `R`
   (L); the topbar after a pause/resume cycle (M). Only JS and CSS changed, so no
   server restart is required.
2. **Re-score C2 on an unbiased statistic.** This is the one genuine measurement
   gap left. Patch `tools/verify_criteria_powered.py` to score `tasks_per_min`
   or an equal-completion-count basis instead of the survivorship-biased
   `avg_completion_s`. Existing config: `SEEDS = (11, 13, 17, 19, 23, 29, 31, 37, 41)`,
   `TICKS = 9000`, `C2_TARGET_PCT = 20.0`, hard-coded `T95` table because scipy
   is not guaranteed. One unattended run, about 40 minutes.
3. **Optional:** raise task supply so `blocked_aisle` is not exhausted inside the
   run window (this is the binding constraint identified in finding 1 above).
4. **Optional:** wire `tools/verify_ui_contract.py` into `run.sh --check` so it
   runs as part of the standard gate.
5. **Owner-side:** rehearse `docs/DEMO_RUN_ORDER.md` against a stopwatch, and
   read `docs/JUDGE_QA_SHEET.md`.

---

## 10. Standing instructions from the project owner

Carry these forward verbatim - they govern how to work on this repo.

- **Implement everything.** *"all the people's work you should be doing now."*
  ACC implements all six modules; do not defer work to a team member.
- **UI/UX is the priority.** *"Give more focus on building best UIUX and
  Simulation as judges will pay more attention on this part. And it should not at
  all look like vibe coded web site."* Vanilla JS + Canvas.
- **Verify your own work.** *"Ensure webpage you build is correct in terms of all
  features and verify yourself that its working as per the features and it must
  win hackathon."* This is the mandate that produced the verifier.
- **Never ask for save permission.** Stated four times. Use the heredoc
  workflow and just write the files.
- **Do not stop at milestone boundaries.** *"please complete the full project...
  dont stop just after one milestone complete... go ahead and complete the entire
  task."*
- **Write a session summary at every milestone boundary.** See the
  `SESSION_SUMMARY_*.md` series.
- ACC has authority to override the four external AI reviews
  (`docs/AI_REVIEW_PROMPT.md`, `from_others/`).

### How the owner iterates
By screenshot, because that is the only channel that can see the rendered page.
When something is wrong, ask for **one screenshot containing the offending thing
and the topbar in the same frame** (so LINK, tick and zoom are all visible),
plus anything the browser console logged. Always run the verifier first - if it
already reports a FAIL, that is the bug and no screenshot is needed.

---

## 11. Commit history at handoff

```
69709c7  docs: session summary for UI round 3 and the contract verifier   <- HEAD
3c02051  UI round 3: fix defects I-M, add headless UI contract verifier
94af5f0  docs: session summary for UI defect round 2 (F, G, H)
6ee6abc  ui: fix three defects found in the second screenshot round (F, G, H)
f47c04c  docs
09074bc  ui round 1
aa8c7f4  C1 criteria
```

## 12. Session summaries, in order

`SESSION_SUMMARY_20260920_1837_team_plan_pptx_and_git.md`,
`..._20260920_2044_four_ai_reviews_and_final_scope.md`,
`..._20260920_2154_m6_complete.md`,
`..._20260920_2238_m4_arbiter_wip.md`,
`..._20260921_0020_collision_metric_defect.md`,
`..._20260921_0050_monitor_throughput.md`,
`..._20260921_0135_fairness_reversal.md`,
`..._20260921_0420_m2_complete.md`,
`..._20260921_0435_m3_advisory_layer.md`,
`..._20260921_1028_m4_containment_green.md`,
`..._20260921_1336_x12_cosim_and_throughput_defect.md`,
`..._20260921_2136_regression_and_master_spec_deck.md`,
`..._20260922_0040_c1_two_defects_root_cause_and_fix.md`,
`..._20260922_0315_ui_defects_from_screenshots.md`,
`..._20260922_0437_ui_round2_F_G_H.md`,
`..._20260922_1050_ui_round3_and_contract_verifier.md`.

Plus `NEXT_PLAN_20260921.md` for the forward plan.

---

## 13. One-paragraph summary for a fresh agent

SWARMOS is a complete, locally-run, framework-free warehouse fleet-coordination
demo for SIH26123 (sponsor BEL): a 10 Hz simulation, a distributed safety
arbiter that provably prevents collisions and contains a rogue robot, an
advisory-only ML layer that is structurally fenced out of the safety path, and a
product-grade Canvas dashboard. All six modules are implemented, 575 tests pass,
and a purpose-built headless verifier (`tools/verify_ui_contract.py`, 22 pass /
1 warn / 0 FAIL) now asserts the UI-to-API contracts that thirteen screenshot-
discovered defects proved the unit tests were blind to. Success criterion C1
(zero collisions) is met; C2 (20 pct throughput gain) is **not** met at -19.3
pct and is reported honestly, with the next step being to re-score it on an
unbiased statistic. Work on this repo using the 3.12 interpreter at
`/pkg/OSS-python-/3.12.0/...`, write files via shell heredoc, edit via
assert-guarded `tools/patch_*.py` scripts, keep code comments ASCII-only, and
remember that the agent shell cannot reach the browser - so verify statically
and in-process, never over live HTTP.
