"""Patch: selectTab must not open the rail during boot.

Section 15 / 24 require state 2 to present the simulation with the side panel
CLOSED. main.js calls selectTab("fleet") once at startup to prime the default
panel, so selectTab's rail-opening side effect has to be opt-in rather than
unconditional. An explicit `opts.reveal` flag keeps the user-initiated paths
(tab click, arrow keys, command palette) opening the rail while the boot call
only sets up which panel WOULD be shown.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


p = ROOT / "web" / "js" / "main.js"
s = p.read_text()

s = sub(
    s,
    """function selectTab(name) {
  activeTab = name;""",
    """/* reveal=true means "the user asked for this panel", so show the rail.
 * reveal=false is the boot path: choose the default panel but leave the rail
 * closed, which is what section 15 requires of state 2. */
function selectTab(name, reveal = true) {
  activeTab = name;""",
    "main.js selectTab signature",
)

s = sub(
    s,
    """  panels[name].render();
  /* Selecting a tab is an explicit request to read that panel, so open the
   * rail. Nothing opens it implicitly: the shell boots with it closed. */
  setRailOpen(true);
}""",
    """  panels[name].render();
  if (reveal) setRailOpen(true);
}""",
    "main.js selectTab reveal guard",
)

s = sub(
    s,
    'selectTab("fleet");\nbuildLegend();',
    'selectTab("fleet", false);   /* panels closed on entry (section 15) */\nbuildLegend();',
    "main.js boot selectTab",
)

p.write_text(s)
print("wrote web/js/main.js")

r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
print("node --check main.js: %s%s" % ("OK" if r.returncode == 0 else "FAIL", r.stderr[:400]))
if r.returncode != 0:
    sys.exit(1)
