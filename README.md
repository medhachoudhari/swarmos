# SWARMOS

**Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots (AMRs)**
SIH26123 — Smart India Hackathon — Team Member 4 (Coordination)

A distributed fleet-coordination system for warehouse AMRs: up to 50 robots
pick and drop tasks on a simulated warehouse floor, coordinated by a
decentralized negotiation layer, backstopped by a hard safety kernel, with an
edge-AI advisory layer strictly outside the safety path, and a live web
dashboard for operators.

No build step, no bundler, no Node.js — the frontend is plain HTML/CSS/vanilla
JavaScript (native ES modules), and the backend is a single Python process.

---

## 1. Clone the repository

```bash
git clone https://github.com/adithyad-cs/swarmos-member4-coordination.git
cd swarmos-member4-coordination
```

If the repository is private, you will need a GitHub account with access,
plus either an SSH key or a Personal Access Token configured on the machine
you are cloning to. If you hit an authentication prompt, use your GitHub
username and a Personal Access Token (not your account password) when asked.

---

## 2. System requirements

| Requirement | Details |
|---|---|
| **Python** | 3.10 or newer (3.11/3.12/3.13 all work). The code uses PEP 604 `X \| Y` type-hint syntax, which fails to import on Python < 3.10. |
| **Python packages** | `starlette`, `uvicorn`, `pydantic` (all on PyPI) |
| **Browser** | Any modern browser — Chrome, Firefox, Edge. No extensions or special settings needed. |
| **OS** | Linux, macOS, or Windows (WSL recommended on Windows for the `run.sh` script; see below for a plain-Python alternative) |
| **Disk / network** | No database server, no external network access needed to run the simulation itself. |

Nothing in this list is specific to any particular company environment or
internal tooling — it is all standard, publicly available software.

**Optional** (only needed for extra, non-essential features):

| Optional package | Needed for |
|---|---|
| `pytest` | Running the automated test suite (`./run.sh --test`) |
| `python-docx` | Regenerating the Word documents in `docs/gen_*_docx.py` |
| `python-pptx` | Regenerating the PowerPoint decks in `docs/gen_*_pptx.py` |
| `websockets` + a local Chrome/Chromium binary | Running the developer diagnostic scripts in `tools/diag_*.py` (not needed to use the product) |

---

## 3. Install dependencies

```bash
python3 --version          # confirm 3.10+
pip install starlette uvicorn pydantic
```

If you also want to run tests or regenerate the docs/PPTs:

```bash
pip install pytest python-docx python-pptx websockets
```

---

## 4. Run it

```bash
./run.sh                 # start the server on port 8770
./run.sh --open          # start, wait for health check, then open a browser
./run.sh --demo          # --open, and also auto-start the reference demo run
./run.sh 8080             # start on a different port
./run.sh --test          # run the automated test suite instead of serving
./run.sh --check         # quick environment sanity check, then exit
```

Then open **http://127.0.0.1:8770/** in your browser (or let `--open`/`--demo`
do it for you).

If `./run.sh` does not work on your system (for example, on plain Windows
without WSL, or if your shell is not bash), start the server directly with
plain Python instead:

```bash
python3 -m uvicorn app.api.server:app --host 127.0.0.1 --port 8770
```

then open `http://127.0.0.1:8770/` yourself.

### Stopping the server

Press `Ctrl-C` in the terminal where it is running.

---

## 5. Run the test suite

```bash
./run.sh --test
```

or directly:

```bash
PYTHONPATH=. python3 -m pytest tests/ -q
```

All 576 tests should pass. If you see a `PluginValidationError` at
collection time, a stale site-wide pytest plugin is interfering; work
around it with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. python3 -m pytest tests/ -q
```

---

## 6. Project layout

```
app/sim/            simulation engine, robot/task/warehouse models, scenarios
app/coordination/   the coordination policy (verdict ladder, safety monitor,
                     adversarial containment)
app/ml/             the advisory-only congestion forecaster
app/db/             persistence and the paired-comparison statistics engine
app/api/            the Starlette web server (REST + websocket)
web/                the browser dashboard (plain HTML/CSS/JS, no build step)
tests/              the automated test suite
tools/              diagnostic and one-off developer scripts
docs/               specification documents, session notes, and the
                    generator scripts for the Word/PPT deliverables
```

See `docs/GRIDLOCK_DEFECT_20260922.md` and `SWARMOS_JUDGE_MASTER_DOCUMENT.docx`
for a full technical write-up of the architecture, feature inventory, and
known-issues history.

---

## 7. Troubleshooting

- **"No module named starlette/uvicorn/pydantic"** — run
  `pip install starlette uvicorn pydantic` (use `pip3` if `pip` points to
  Python 2 on your system).
- **"ENTER SWARMOS" button does nothing when opening `web/landing.html`
  directly from disk (`file://...`)** — this is expected and handled: the
  page will navigate you to the running server's own copy of the page on
  the first click; click **ENTER SWARMOS** a second time there to actually
  start the simulation. This only applies if you open the HTML file
  directly instead of using `./run.sh`.
- **Port 8770 already in use** — pass a different port:
  `./run.sh 8080`, then open `http://127.0.0.1:8080/`.
