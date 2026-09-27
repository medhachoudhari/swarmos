"""Round 3b. Two fixes the new contract verifier itself found.

1. tokens.css: my round-3 --map-grid-major (#2E3B47) came out BRIGHTER than
   --line-default (#263039), which breaks the design law that map decoration
   must stay quieter than data ink. Dialled back to sit just under it while
   keeping enough contrast against --map-floor to read on a projector.
2. map.js: the rack-outline and dock-label gates still compared px-per-metre
   against bare literals 6 and 10 - the same unnamed-threshold smell that
   caused defect J. Given names.
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


def load(rel):
    with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


pending = {}

TOK = "web/styles/tokens.css"
tok = load(TOK)
tok = sub(
    tok,
    "  --map-grid: #1E2832;\n  --map-grid-major: #2E3B47;",
    "  --map-grid: #1B242C;\n  --map-grid-major: #232D36;",
    "3b grid tokens",
)
pending[TOK] = tok

MAP = "web/js/map.js"
mp = load(MAP)
mp = sub(
    mp,
    "const GRID_MINOR_PX_PER_M = 10;   // below this, major lines only",
    "const GRID_MINOR_PX_PER_M = 10;   // below this, major lines only\n"
    "const RACK_OUTLINE_PX_PER_M = 6;  // below this, racks are filled but not outlined\n"
    "const DOCK_LABEL_PX_PER_M = 10;   // below this, dock labels are unreadable",
    "3b new consts",
)
mp = sub(
    mp,
    "        if (s >= 6) ctx.strokeRect(",
    "        if (s >= RACK_OUTLINE_PX_PER_M) ctx.strokeRect(",
    "3b rack outline",
)
mp = sub(
    mp,
    "    if (Array.isArray(wh.docks) && s >= 10) {",
    "    if (Array.isArray(wh.docks) && s >= DOCK_LABEL_PX_PER_M) {",
    "3b dock label",
)
pending[MAP] = mp

for rel, text in pending.items():
    with io.open(os.path.join(ROOT, rel), "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s" % rel)
