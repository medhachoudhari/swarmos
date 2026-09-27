"""Patch: route "/" to the ROBONEX landing page, and make the desktop rail
closable and closed by default.

Two changes, both additive:

  1. app/api/server.py  - an explicit Route("/") that serves web/landing.html.
     The StaticFiles mount stays exactly where it is and still serves
     /index.html, so the dashboard keeps its own URL and nothing else moves.

  2. web/index.html + web/styles/shell.css + web/js/main.js - the rail is a
     real column at desktop widths and previously could not be closed at all
     (.rail-toggle was display:none above 1280px). It now starts closed and
     the handle works at every width.

Every substitution is guarded on an exact single match, and all files are
written only after every substitution has succeeded.
"""

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


pending = {}

# ---------------------------------------------------------------- server.py

p = ROOT / "app" / "api" / "server.py"
s = p.read_text()

s = sub(
    s,
    "from starlette.responses import JSONResponse\n",
    "from starlette.responses import FileResponse, JSONResponse\n",
    "server.py FileResponse import",
)

s = sub(
    s,
    """    GET  /api/cosim/status
    WS   /ws/fleet
    WS   /ws/cosim
""",
    """    GET  /api/cosim/status
    WS   /ws/fleet
    WS   /ws/cosim

Two HTML entry points are served:

    GET  /             web/landing.html   ROBONEX landing page  (state 1)
    GET  /index.html   web/index.html     SWARMOS dashboard     (states 2, 3)

"/" needs its own route because the StaticFiles mount resolves a bare "/" to
index.html by itself, which would skip the landing page entirely. The mount
still serves index.html and every other asset, so the dashboard URL is
unchanged and no simulation behaviour is touched.
""",
    "server.py route contract docstring",
)

s = sub(
    s,
    """async def health(request: Request) -> JSONResponse:
    return _ok({"service": "swarmos", "has_run": manager.has_run})
""",
    """async def health(request: Request) -> JSONResponse:
    return _ok({"service": "swarmos", "has_run": manager.has_run})


# --------------------------------------------------------------------------
# html entry points
# --------------------------------------------------------------------------

async def landing(request: Request):
    \"\"\"Serve the ROBONEX landing page at "/".

    Falls back to the dashboard if landing.html is ever missing, so a partial
    checkout degrades into the working product rather than a 404.
    \"\"\"
    page = WEB_DIR / "landing.html"
    if not page.is_file():
        page = WEB_DIR / "index.html"
    return FileResponse(str(page), media_type="text/html")
""",
    "server.py landing handler",
)

s = sub(
    s,
    """    WebSocketRoute("/ws/fleet", ws_fleet),
    WebSocketRoute("/ws/cosim", ws_cosim),
]""",
    """    WebSocketRoute("/ws/fleet", ws_fleet),
    WebSocketRoute("/ws/cosim", ws_cosim),
    # Declared before the StaticFiles mount below, which would otherwise
    # resolve "/" to index.html and never reach the landing page.
    Route("/", landing, methods=["GET"]),
]""",
    "server.py landing route registration",
)

pending[p] = s

# ---------------------------------------------------------------- index.html

p = ROOT / "web" / "index.html"
s = p.read_text()
s = sub(
    s,
    '<div class="shell">',
    '<div class="shell" id="shell" data-rail="closed">',
    "index.html shell data-rail",
)
pending[p] = s

# ---------------------------------------------------------------- shell.css

p = ROOT / "web" / "styles" / "shell.css"
s = p.read_text()

s = sub(
    s,
    """/* The handle is hidden at desktop widths, where the rail is a real column and
 * there is nothing to toggle. The sub-1280px block above re-enables it. */
.rail-toggle { display: none; }""",
    """/* The handle is available at every width. The rail is a real column above
 * 1280px and an overlay drawer below it, but in both cases the operator must
 * be able to put it away and get the whole floor back. */
.rail-toggle { display: inline-flex; }

/* Desktop: a closed rail gives its column width back to the map instead of
 * merely hiding itself, so there is no dead gutter beside the warehouse. The
 * sub-1280px drawer rules are left untouched; they key off .rail[data-open]. */
@media (min-width: 1281px) {
  .shell[data-rail="closed"] {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "topbar"
      "map"
      "strip";
  }
  .shell[data-rail="closed"] > .rail { display: none; }
}""",
    "shell.css desktop closable rail",
)
pending[p] = s

# ---------------------------------------------------------------- main.js

p = ROOT / "web" / "js" / "main.js"
s = p.read_text()

s = sub(
    s,
    """  panels[name].render();
  const rail = $("rail");
  if (rail && window.innerWidth < 1280) {
    rail.dataset.open = "true";
    const handle = $("btn-rail-toggle");
    if (handle) handle.setAttribute("aria-expanded", "true");
  }
}""",
    """  panels[name].render();
  /* Selecting a tab is an explicit request to read that panel, so open the
   * rail. Nothing opens it implicitly: the shell boots with it closed. */
  setRailOpen(true);
}""",
    "main.js selectTab rail open",
)

s = sub(
    s,
    """/* Below 1280px the rail is an overlay drawer. A drawer with no visible handle
 * is a trap, so the topbar carries one at those widths. */
$("btn-rail-toggle") && $("btn-rail-toggle").addEventListener("click", () => {
  const rail = $("rail");
  if (!rail) return;
  const open = rail.dataset.open !== "true";
  rail.dataset.open = String(open);
  $("btn-rail-toggle").setAttribute("aria-expanded", String(open));
});""",
    """/* One toggle, two mechanisms. Above 1280px the rail is a grid column and the
 * shell gives its width back to the map; below, it is an overlay drawer. Both
 * are driven from the same handle so the keyboard path is identical. */
function isRailOpen() {
  const shell = $("shell");
  const rail = $("rail");
  if (shell && window.innerWidth > 1280) return shell.dataset.rail === "open";
  return !!rail && rail.dataset.open === "true";
}

function setRailOpen(open) {
  const shell = $("shell");
  const rail = $("rail");
  if (shell) shell.dataset.rail = open ? "open" : "closed";
  if (rail) rail.dataset.open = String(open);
  const handle = $("btn-rail-toggle");
  if (handle) handle.setAttribute("aria-expanded", String(open));
}

$("btn-rail-toggle") && $("btn-rail-toggle").addEventListener("click", () => {
  setRailOpen(!isRailOpen());
});""",
    "main.js rail toggle",
)

pending[p] = s

# ---------------------------------------------------------------- write + gate

for path, text in pending.items():
    path.write_text(text)
    print("wrote %s" % path.relative_to(ROOT))

ast.parse((ROOT / "app" / "api" / "server.py").read_text())
print("ast.parse server.py OK")

r = subprocess.run(
    ["node", "--check", str(ROOT / "web" / "js" / "main.js")],
    capture_output=True,
    text=True,
)
print("node --check main.js: %s%s" % ("OK" if r.returncode == 0 else "FAIL", r.stderr[:400]))
if r.returncode != 0:
    sys.exit(1)
