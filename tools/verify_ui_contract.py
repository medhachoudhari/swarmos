#!/usr/bin/env python3
"""Headless UI contract verifier for SWARMOS.

WHY THIS EXISTS
---------------
Three consecutive rounds of UI defects (A-E, F-H, I-M) had one thing in
common: every single one was a CONTRACT that no test asserted. The bugs were
not logic errors inside a function, they were disagreements between two files.

  - lab.js read s.id while the server emits s.name        -> defect I
  - main.js advertised key "0" that nothing bound          -> defect L
  - map.js compared a px threshold against a zoom ratio    -> defect J, K
  - panels.css styled a class the JS never emitted         -> defects F, G
  - transport.js read "error" while the server sent "detail" -> round 1

This script asserts those cross-file contracts deterministically, with no
browser. It is not a replacement for looking at the page - canvas pixels,
focus rings and motion still need a human eye, and docs/UI_VERIFICATION_
CHECKLIST.md covers those. It IS a guarantee that the wiring is sound before
anyone looks.

USAGE
    PYTHONPATH=. python3 tools/verify_ui_contract.py
    PYTHONPATH=. python3 tools/verify_ui_contract.py --no-api   (static only)

Exit code 0 = every contract holds. 1 = at least one FAIL.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

RESULTS = []          # (level, check, message) ; level in PASS / WARN / FAIL


def record(level, check, message):
    RESULTS.append((level, check, message))


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def js_files():
    out = []
    for base, _dirs, names in os.walk(os.path.join(WEB, "js")):
        for n in sorted(names):
            if n.endswith(".js"):
                out.append(os.path.join(base, n))
    return out


def css_files():
    d = os.path.join(WEB, "styles")
    return [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".css")]


def rel(path):
    return os.path.relpath(path, ROOT)


# --------------------------------------------------------------------------
# strip comments so that documentation never trips a check
# --------------------------------------------------------------------------

def strip_js_comments(src):
    # Good enough for this codebase: no regex literals contain // or /*.
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"(?m)([^:\"'`])//[^\"'`\n]*$", r"\1", src)
    return src


# --------------------------------------------------------------------------
# 1. every DOM id the JS reaches for must exist somewhere
# --------------------------------------------------------------------------

def html_files():
    return [os.path.join(WEB, n) for n in sorted(os.listdir(WEB)) if n.endswith(".html")]


def check_dom_ids():
    # Two entry points now: index.html is the dashboard, landing.html is the
    # ROBONEX landing page. An id declared in either one is available.
    html = "\n".join(read(path) for path in html_files())
    html_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))

    # Ids that panels mint themselves inside innerHTML template strings.
    minted = set()
    for path in js_files():
        src = read(path)
        minted |= set(re.findall(r'id="([A-Za-z0-9_-]+)"', src))
        minted |= set(re.findall(r"id='([A-Za-z0-9_-]+)'", src))

    available = html_ids | minted
    missing = []
    wanted = set()
    for path in js_files():
        src = strip_js_comments(read(path))
        for m in re.finditer(r'\$\(\s*"([A-Za-z0-9_-]+)"\s*\)', src):
            wanted.add((m.group(1), rel(path)))
        for m in re.finditer(r'getElementById\(\s*"([A-Za-z0-9_-]+)"\s*\)', src):
            wanted.add((m.group(1), rel(path)))
        for m in re.finditer(r'querySelector\(\s*"#([A-Za-z0-9_-]+)"\s*\)', src):
            wanted.add((m.group(1), rel(path)))

    for ident, where in sorted(wanted):
        if ident not in available:
            missing.append("%s wants #%s which no HTML or template defines" % (where, ident))

    if missing:
        for m in missing:
            record("FAIL", "dom-ids", m)
    else:
        record("PASS", "dom-ids", "%d referenced ids all resolve" % len(wanted))

    # Informational: declared and never touched. Not a failure - some ids are
    # pure CSS or aria anchors.
    touched = {i for i, _ in wanted}
    orphan = sorted(i for i in html_ids if i not in touched)
    if orphan:
        record("WARN", "dom-ids", "declared in html, never read by JS: %s"
               % ", ".join(orphan))


# --------------------------------------------------------------------------
# 2. <option value> must carry a key the server actually accepts
#    This is the check that catches defect I statically.
# --------------------------------------------------------------------------

def check_option_values():
    lab = read(os.path.join(WEB, "js", "panels", "lab.js"))

    # Scenario select. The template must interpolate a FIELD of the record,
    # never the record itself, or the value stringifies to [object Object].
    m = re.search(r'<option value="\$\{([^}]+)\}">', lab)
    if not m:
        record("FAIL", "option-values", "lab.js: no scenario option template found")
        return
    expr = m.group(1).strip()
    if re.search(r"\|\|\s*s\s*$", expr) or expr == "s":
        record("FAIL", "option-values",
               "lab.js scenario option value is `%s` - a fallback to the whole "
               "record stringifies to [object Object]" % expr)
    else:
        record("PASS", "option-values", "lab.js scenario option value is `%s`" % expr)

    field = expr.split(".")[-1].split(" ")[0]
    try:
        from app.sim.scenarios import list_scenarios
    except Exception as exc:                                  # pragma: no cover
        record("WARN", "option-values", "cannot import list_scenarios: %s" % exc)
        return
    rows = list_scenarios()
    bad = [r for r in rows if not r.get(field)]
    if bad:
        record("FAIL", "option-values",
               "list_scenarios() rows lack field '%s' (keys are %s)"
               % (field, sorted(rows[0].keys())))
    else:
        record("PASS", "option-values",
               "all %d scenarios expose '%s': %s"
               % (len(rows), field, ", ".join(r[field] for r in rows)))

    # Fault select. Ids in lab.js must be accepted by the runner, which maps
    # lower-case ui ids onto FaultKind through _FAULT_ALIASES.
    fault_ids = re.findall(r'\{\s*id:\s*"([a-z_]+)"', lab)
    try:
        from app.api.runner import _FAULT_ALIASES
        from app.sim.scenarios import FaultKind
    except Exception as exc:                                  # pragma: no cover
        record("WARN", "option-values", "cannot import fault tables: %s" % exc)
        return
    known = {k.value for k in FaultKind}
    unknown = [f for f in fault_ids
               if _FAULT_ALIASES.get(f, f.upper()) not in known
               and _FAULT_ALIASES.get(f, f) not in known]
    if unknown:
        record("FAIL", "option-values",
               "lab.js offers faults the engine does not know: %s" % ", ".join(unknown))
    else:
        record("PASS", "option-values",
               "all %d offered faults map onto FaultKind" % len(fault_ids))


# --------------------------------------------------------------------------
# 3. every advertised keystroke must be bound
#    This is the check that catches defect L.
# --------------------------------------------------------------------------

KEY_ALIASES = {
    "esc": ("escape",),
    "escape": ("escape",),
    "ctrl+k": ("k",),
    "cmd+k": ("k",),
}


def _bound_keys(main):
    keys = set()
    for m in re.finditer(r'e\.key\s*===\s*"([^"]+)"', main):
        keys.add(m.group(1).lower())
    return keys


def check_keyboard():
    main = strip_js_comments(read(os.path.join(WEB, "js", "main.js")))
    bound = _bound_keys(main)
    for path in js_files():
        if path.endswith("palette.js"):
            bound |= _bound_keys(strip_js_comments(read(path)))

    advertised = set()
    for m in re.finditer(r'hint:\s*"([^"]+)"', main):
        advertised.add(m.group(1))
    trn = read(os.path.join(WEB, "js", "transport.js"))
    for m in re.finditer(r"press ([A-Za-z0-9]+) to", trn):
        advertised.add(m.group(1))

    unbound = []
    for a in sorted(advertised):
        cands = KEY_ALIASES.get(a.lower(), (a.lower(),))
        if not any(c in bound for c in cands):
            unbound.append(a)
    if unbound:
        record("FAIL", "keyboard",
               "advertised but not bound anywhere: %s (bound keys: %s)"
               % (", ".join(unbound), ", ".join(sorted(bound))))
    else:
        record("PASS", "keyboard",
               "every advertised key is bound (%s)" % ", ".join(sorted(advertised)))

    # A global handler that does not guard text fields will eat typing.
    if "typingTarget" not in main and "tagName" not in main:
        record("FAIL", "keyboard",
               "main.js global keydown has no input-focus guard - single-letter "
               "shortcuts will fire while the operator types")
    else:
        record("PASS", "keyboard", "global keydown guards text entry")


# --------------------------------------------------------------------------
# 4. every css() token must be declared, and the map grid must be visible
#    This is the check that catches defect J.
# --------------------------------------------------------------------------

def _hex(v):
    v = v.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    if len(v) != 6:
        return None
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    # Relative luminance, sRGB.
    def lin(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def check_tokens():
    declared = {}
    for path in css_files():
        for m in re.finditer(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", read(path)):
            declared.setdefault(m.group(1), m.group(2).strip())

    used = set()
    for path in js_files():
        for m in re.finditer(r'css\(\s*"(--[a-z0-9-]+)"\s*\)', read(path)):
            used.add((m.group(1), rel(path)))

    missing = [(t, w) for t, w in sorted(used) if t not in declared]
    if missing:
        for t, w in missing:
            record("FAIL", "tokens", "%s uses %s which no stylesheet declares" % (w, t))
    else:
        record("PASS", "tokens", "%d canvas tokens all declared" % len({t for t, _ in used}))

    floor = _hex(declared.get("--map-floor", ""))
    for name, floor_min in (("--map-grid", 1.12), ("--map-grid-major", 1.25)):
        rgb = _hex(declared.get(name, ""))
        if not (floor and rgb):
            record("WARN", "tokens", "cannot parse %s or --map-floor" % name)
            continue
        c = _contrast(rgb, floor)
        if c < floor_min:
            record("FAIL", "tokens",
                   "%s vs --map-floor contrast %.3f is below the %.2f floor - "
                   "the grid will not read on a projector" % (name, c, floor_min))
        else:
            record("PASS", "tokens", "%s vs --map-floor contrast %.3f" % (name, c))

    # The grid must stay quieter than a panel edge, or decoration out-inks data.
    line = _hex(declared.get("--line-default", ""))
    major = _hex(declared.get("--map-grid-major", ""))
    if line and major and floor:
        if _lum(major) > _lum(line):
            record("FAIL", "tokens",
                   "--map-grid-major is brighter than --line-default - grid "
                   "decoration would compete with data ink")
        else:
            record("PASS", "tokens", "--map-grid-major stays below --line-default")


# --------------------------------------------------------------------------
# 5. thresholds must be compared against the quantity they are named for
#    This is the check that catches defect K.
# --------------------------------------------------------------------------

def check_map_thresholds():
    src = strip_js_comments(read(os.path.join(WEB, "js", "map.js")))
    bad = []
    for m in re.finditer(r"this\.zoom\s*[<>]=?\s*([A-Z_]+)", src):
        if "PX_PER_M" in m.group(1):
            bad.append("this.zoom compared against %s" % m.group(1))
    for m in re.finditer(r"([A-Z_]+)\s*[<>]=?\s*this\.zoom", src):
        if "PX_PER_M" in m.group(1):
            bad.append("%s compared against this.zoom" % m.group(1))
    for m in re.finditer(r"\bs\s*[<>]=?\s*([A-Z_]+ZOOM)\b", src):
        bad.append("px-per-metre compared against %s" % m.group(1))
    if bad:
        for b in bad:
            record("FAIL", "map-units", b + " - unit mismatch")
    else:
        record("PASS", "map-units", "all named map thresholds compared in their own unit")

    # Bare numeric literals in the level-of-detail gates are how J happened.
    for m in re.finditer(r"\bs\s*[<>]=?\s*([0-9]+)\b", src):
        record("WARN", "map-units",
               "map.js compares px-per-metre against the bare literal %s - "
               "give it a named constant" % m.group(1))


# --------------------------------------------------------------------------
# 6. every class the JS emits must be styled somewhere
#    This is the class of bug that produced F and G.
# --------------------------------------------------------------------------

def check_css_classes():
    styled = set()
    for path in css_files():
        for m in re.finditer(r"\.([A-Za-z][A-Za-z0-9_-]*)", read(path)):
            styled.add(m.group(1))

    used = {}
    for path in js_files():
        src = read(path)
        for m in re.finditer(r'class="([^"$]*)"', src):
            for cls in m.group(1).split():
                if "${" in cls:
                    continue
                used.setdefault(cls, rel(path))
    html = read(os.path.join(WEB, "index.html"))
    for m in re.finditer(r'class="([^"]*)"', html):
        for cls in m.group(1).split():
            used.setdefault(cls, "web/index.html")

    missing = sorted((c, w) for c, w in used.items() if c not in styled)
    if missing:
        for c, w in missing:
            record("WARN", "css-classes", "%s emits .%s which no stylesheet targets" % (w, c))
    else:
        record("PASS", "css-classes", "%d emitted classes all styled" % len(used))


# --------------------------------------------------------------------------
# 7. in-process API smoke. The end-to-end form of check 2.
# --------------------------------------------------------------------------

def check_api():
    try:
        from starlette.testclient import TestClient

        from app.api.server import app
        from app.sim.scenarios import FaultKind
    except Exception as exc:
        record("WARN", "api", "cannot import the app: %s" % exc)
        return

    def ok(resp):
        if resp.status_code != 200:
            return False, "HTTP %d %s" % (resp.status_code, str(resp.json())[:160])
        body = resp.json()
        if isinstance(body, dict) and body.get("ok") is False:
            return False, str(body.get("error") or body)[:160]
        return True, ""

    with TestClient(app) as c:
        r = c.get("/api/scenarios")
        good, why = ok(r)
        if not good:
            record("FAIL", "api", "GET /api/scenarios: %s" % why)
            return
        body = r.json()
        rows = body["scenarios"] if isinstance(body, dict) else body
        names = [row["name"] for row in rows]
        record("PASS", "api", "GET /api/scenarios -> %s" % ", ".join(names))

        # Every name the dropdown can offer must start a run. This is the
        # end-to-end assertion that defect I violated.
        for name in names:
            c.post("/api/sim/stop")
            good, why = ok(c.post("/api/sim/start",
                                  json={"scenario": name, "seed": 11, "fleet_size": 6}))
            if not good:
                record("FAIL", "api", "start '%s': %s" % (name, why))
                continue
            for path, payload in (("/api/sim/step", {"ticks": 1}),
                                  ("/api/sim/pause", {}),
                                  ("/api/sim/resume", {}),
                                  ("/api/sim/pause", {})):
                good, why = ok(c.post(path, json=payload))
                if not good:
                    record("FAIL", "api", "%s after start '%s': %s" % (path, name, why))
            record("PASS", "api", "start/step/pause/resume ok for '%s'" % name)

        # One injection per fault the UI can offer, against a live run.
        c.post("/api/sim/stop")
        good, why = ok(c.post("/api/sim/start",
                              json={"scenario": names[0], "seed": 11, "fleet_size": 6}))
        if good:
            lab = read(os.path.join(WEB, "js", "panels", "lab.js"))
            ui_faults = re.findall(r'\{\s*id:\s*"([a-z_]+)"', lab)
            for f in ui_faults:
                good, why = ok(c.post("/api/sim/inject", json={"fault": f}))
                if not good:
                    record("FAIL", "api", "inject '%s': %s" % (f, why))
                else:
                    record("PASS", "api", "inject '%s' accepted" % f)
            record("PASS", "api", "%d of %d FaultKind values are reachable from the UI"
                   % (len(ui_faults), len(list(FaultKind))))
        c.post("/api/sim/stop")


# --------------------------------------------------------------------------
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
    if re.search(r"^\.rail-toggle\s*\{\s*display:\s*none", shell, re.M):
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
    wanted = set(re.findall(r"\bwh\.([A-Za-z_][A-Za-z0-9_]*)", src))
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
    produced = set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", store, re.M))
    missing = sorted(k for k in wanted if k not in produced and k not in store)
    if missing:
        for k in missing:
            record("FAIL", "render-payload",
                   "map.js reads wh.%s which normaliseWarehouse never produces" % k)
    else:
        record("PASS", "render-payload",
               "all %d warehouse keys map.js reads are produced by the normaliser" % len(wanted))


# --------------------------------------------------------------------------

CHECKS = [
    ("dom-ids", check_dom_ids),
    ("option-values", check_option_values),
    ("keyboard", check_keyboard),
    ("tokens", check_tokens),
    ("map-units", check_map_thresholds),
    ("css-classes", check_css_classes),
    ("landing", check_landing),
    ("rail-default", check_rail_default),
    ("render-payload", check_render_payload),
]


def main(argv):
    run_api = "--no-api" not in argv
    for _name, fn in CHECKS:
        try:
            fn()
        except Exception as exc:
            record("FAIL", _name, "checker itself raised: %r" % exc)
    if run_api:
        try:
            check_api()
        except Exception as exc:
            record("FAIL", "api", "checker itself raised: %r" % exc)

    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    width = max(len(c) for _l, c, _m in RESULTS)
    print("")
    print("SWARMOS UI CONTRACT VERIFIER")
    print("=" * 78)
    for level in ("FAIL", "WARN", "PASS"):
        rows = [r for r in RESULTS if r[0] == level]
        for _l, check, msg in rows:
            print("%-4s  %-*s  %s" % (level, width, check, msg))
    fails = sum(1 for l, _c, _m in RESULTS if l == "FAIL")
    warns = sum(1 for l, _c, _m in RESULTS if l == "WARN")
    passes = sum(1 for l, _c, _m in RESULTS if l == "PASS")
    print("-" * 78)
    print("%d pass, %d warn, %d FAIL" % (passes, warns, fails))
    print("")
    if fails:
        print("Contracts are broken. Fix them before looking at the page.")
    else:
        print("All machine-checkable UI contracts hold.")
        print("Now walk docs/UI_VERIFICATION_CHECKLIST.md for the things only")
        print("a human eye can confirm (canvas pixels, focus rings, motion).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
