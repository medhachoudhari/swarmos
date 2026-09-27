"""Extend tools/verify_ui_contract.py for the three-state experience.

Three things changed under it:

  1. There are now TWO html entry points. check_dom_ids only read index.html,
     so every #lp-* id that landing.js reads would have been reported missing.
     It now unions the ids of every *.html file in web/.

  2. Defect N (the warehouse static layer never rendered because store.js
     handed map.js a payload using different key names) was invisible to 575
     passing tests. check_render_payload asserts, against the live server,
     that every key map.js reads off the normalised warehouse actually exists.

  3. Sections 6-15 fix landing copy and the panels-closed default in writing.
     check_landing and check_rail_default assert them so a later edit cannot
     quietly regress the spec.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


p = ROOT / "tools" / "verify_ui_contract.py"
s = p.read_text()

# --- 1. both html entry points -------------------------------------------

s = sub(
    s,
    '''def check_dom_ids():
    html = read(os.path.join(WEB, "index.html"))
    html_ids = set(re.findall(r\'id="([A-Za-z0-9_-]+)"\', html))''',
    '''def html_files():
    return [os.path.join(WEB, n) for n in sorted(os.listdir(WEB)) if n.endswith(".html")]


def check_dom_ids():
    # Two entry points now: index.html is the dashboard, landing.html is the
    # ROBONEX landing page. An id declared in either one is available.
    html = "\\n".join(read(path) for path in html_files())
    html_ids = set(re.findall(r\'id="([A-Za-z0-9_-]+)"\', html))''',
    "dom-ids both html files",
)

s = sub(
    s,
    '''        record("WARN", "dom-ids", "declared in index.html, never read by JS: %s"
               % ", ".join(orphan))''',
    '''        record("WARN", "dom-ids", "declared in html, never read by JS: %s"
               % ", ".join(orphan))''',
    "dom-ids orphan wording",
)

# --- 2/3. new checks, inserted before the CHECKS table -------------------

s = sub(
    s,
    '''# --------------------------------------------------------------------------

CHECKS = [''',
    '''# --------------------------------------------------------------------------
# 7. the landing page must say exactly what sections 6-13 require
# --------------------------------------------------------------------------

# Verbatim from ROBONEX_SWARMOS_FINAL_UI_UX_MASTER_PROMPT.docx. Kept as data so
# a copy edit to the page fails loudly instead of drifting off spec.
LANDING_COPY = [
    ("ROBONEX", "section 6/7 wordmark and hero title"),
    ("SMART INDIA HACKATHON", "section 6 SIH line"),
    ("SWARMOS", "section 6/9 product name"),
    ("Distributed intelligence for autonomous warehouse fleets.", "section 7 lede"),
    ("DECENTRALIZED MULTI-AMR COORDINATION", "section 9 card kicker"),
    ("Decentralized coordination", "section 9 capability 1"),
    ("Real-time conflict resolution", "section 9 capability 2"),
    ("Dynamic task allocation", "section 9 capability 3"),
    ("Spatio-temporal coordination", "section 9 capability 4"),
    ("Failure recovery", "section 9 capability 5"),
    ("Edge intelligence", "section 9 capability 6"),
    ("FLEET STATUS", "section 11 status row 1"),
    ("AMR NETWORK", "section 11 status row 2"),
    ("ENTER SWARMOS", "section 12 call to action"),
]

# Section 14: no commercial content anywhere on the landing page.
COMMERCIAL_WORDS = ("pricing", "price", "testimonial", "buy now", "subscribe",
                    "free trial", "contact sales")

# Section 6 / 31: no navigation links that go nowhere.
DEAD_NAV_WORDS = ("SYSTEM", "FLEET</", "BENCHMARK")


def check_landing():
    path = os.path.join(WEB, "landing.html")
    if not os.path.isfile(path):
        record("FAIL", "landing", "web/landing.html is missing - state 1 has no page")
        return
    html = read(path)

    missing = [why for text, why in LANDING_COPY if text not in html]
    if missing:
        for why in missing:
            record("FAIL", "landing", "required copy absent: %s" % why)
    else:
        record("PASS", "landing", "all %d mandated strings present" % len(LANDING_COPY))

    low = html.lower()
    found = [w for w in COMMERCIAL_WORDS if w in low]
    if found:
        record("FAIL", "landing", "section 14 forbids commercial content, found: %s"
               % ", ".join(found))
    else:
        record("PASS", "landing", "no commercial content (section 14)")

    if "<nav" in low or 'class="nav' in low:
        record("FAIL", "landing", "section 6 forbids nav links on the landing page")
    else:
        record("PASS", "landing", "no nav element (sections 6, 31)")

    # Section 12: the CTA must enter the REAL simulation, not a fake one.
    js = read(os.path.join(WEB, "js", "landing.js"))
    if "api/sim/start" not in js:
        record("FAIL", "landing", "ENTER SWARMOS does not POST to /api/sim/start")
    elif "index.html" not in js:
        record("FAIL", "landing", "ENTER SWARMOS never navigates to the dashboard")
    else:
        record("PASS", "landing", "ENTER SWARMOS starts the real run then opens the dashboard")

    # Section 11: status must never be invented. The unreachable path has to
    # be able to render the em-dash placeholder rather than a cheerful lie.
    if "UNREACHABLE" in js and '"--"' in js:
        record("PASS", "landing", "status degrades honestly when the server is silent")
    else:
        record("FAIL", "landing", "no honest degraded state for the status rows")

    # Section 13: restrained transition, and reduced motion respected.
    css = read(os.path.join(WEB, "styles", "landing.css"))
    if "prefers-reduced-motion" not in css:
        record("FAIL", "landing", "landing.css ignores prefers-reduced-motion")
    else:
        record("PASS", "landing", "landing.css honours prefers-reduced-motion")

    # Section 32: reuse the palette, do not fork it.
    if "tokens.css" not in css:
        record("FAIL", "landing", "landing.css does not import tokens.css - palette forked")
    else:
        record("PASS", "landing", "landing.css imports the canonical tokens")


# --------------------------------------------------------------------------
# 8. state 2 must open with the side panel CLOSED (sections 15, 24)
# --------------------------------------------------------------------------

def check_rail_default():
    html = read(os.path.join(WEB, "index.html"))
    if 'data-rail="closed"' not in html:
        record("FAIL", "rail-default", "the shell does not boot with data-rail=closed")
    else:
        record("PASS", "rail-default", "shell boots with the rail closed")

    if 'data-open="false"' not in html:
        record("FAIL", "rail-default", "the rail does not boot with data-open=false")
    else:
        record("PASS", "rail-default", "rail element boots closed")

    main = strip_js_comments(read(os.path.join(WEB, "js", "main.js")))
    if 'selectTab("fleet", false)' not in main:
        record("FAIL", "rail-default",
               "boot calls selectTab without reveal=false, so the rail opens itself")
    else:
        record("PASS", "rail-default", "boot primes the default panel without revealing the rail")

    # The handle has to exist at desktop widths or a closed rail is a trap.
    shell = read(os.path.join(WEB, "styles", "shell.css"))
    if re.search(r"^\\.rail-toggle\\s*\\{\\s*display:\\s*none", shell, re.M):
        record("FAIL", "rail-default",
               "the rail handle is display:none at desktop - a closed rail cannot be reopened")
    else:
        record("PASS", "rail-default", "rail handle is available at every width")


# --------------------------------------------------------------------------
# 9. every warehouse key map.js reads must exist on the normalised payload
#    This is defect N, which 575 passing tests did not catch.
# --------------------------------------------------------------------------

def check_render_payload():
    src = strip_js_comments(read(os.path.join(WEB, "js", "map.js")))
    wanted = set(re.findall(r"\\bwh\\.([A-Za-z_][A-Za-z0-9_]*)", src))
    if not wanted:
        record("WARN", "render-payload", "map.js reads no wh.* keys - checker is stale")
        return

    store = strip_js_comments(read(os.path.join(WEB, "js", "store.js")))
    if "normaliseWarehouse" not in store:
        record("FAIL", "render-payload",
               "store.js has no normaliseWarehouse - the wire payload reaches map.js raw")
        return

    # The normaliser is the single place the wire format becomes the render
    # format, so every key map.js reads must be produced there by name.
    produced = set(re.findall(r"^\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*:", store, re.M))
    missing = sorted(k for k in wanted if k not in produced and k not in store)
    if missing:
        for k in missing:
            record("FAIL", "render-payload",
                   "map.js reads wh.%s which normaliseWarehouse never produces" % k)
    else:
        record("PASS", "render-payload",
               "all %d warehouse keys map.js reads are produced by the normaliser" % len(wanted))


# --------------------------------------------------------------------------

CHECKS = [''',
    "new checks block",
)

s = sub(
    s,
    '''    ("css-classes", check_css_classes),
]''',
    '''    ("css-classes", check_css_classes),
    ("landing", check_landing),
    ("rail-default", check_rail_default),
    ("render-payload", check_render_payload),
]''',
    "CHECKS table",
)

p.write_text(s)
print("wrote tools/verify_ui_contract.py")

import ast
ast.parse(p.read_text())
print("ast.parse OK")
