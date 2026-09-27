"""Final geometry correction for the in-flow banner.

Leaving height:100dvh on .shell while the banner also occupies flow height sums
to more than the viewport, and body has overflow:hidden - so the telemetry
strip would be clipped exactly when a banner is showing, which is precisely
when the operator most needs the numbers. As a flex item of a definite-height
column, flex:1 1 0 gives the shell a definite height equal to whatever the
banner left over, so the 68/22/10 percentages still resolve against a real
number and the strip is never clipped.
"""

ROOT = "/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920"

path = ROOT + "/web/styles/shell.css"
with open(path) as fh:
    src = fh.read()
old = """  /* The banner is in flow above us, so claim the remaining height rather than
   * the whole viewport - otherwise the telemetry strip would be pushed off. */
  height: 100vh;
  height: 100dvh;
  flex: 1 1 auto;
  min-height: 0;"""
new = """  /* Take the height the banner left over, not the whole viewport. A flex item
   * of a definite-height column has a definite height itself, so the 68/22/10
   * percentages below still resolve and the strip is never clipped. */
  flex: 1 1 0;
  min-height: 0;"""
assert src.count(old) == 1
src = src.replace(old, new)
with open(path, "w") as fh:
    fh.write(src)
print("shell height corrected")

# The rail drawer is forced open when a tab is chosen at narrow widths. The
# handle's aria-expanded must follow, or assistive tech is told the opposite of
# what the screen shows.
path = ROOT + "/web/js/main.js"
with open(path) as fh:
    src = fh.read()
old = """  const rail = $("rail");
  if (rail && window.innerWidth < 1280) rail.dataset.open = "true";"""
new = """  const rail = $("rail");
  if (rail && window.innerWidth < 1280) {
    rail.dataset.open = "true";
    const handle = $("btn-rail-toggle");
    if (handle) handle.setAttribute("aria-expanded", "true");
  }"""
assert src.count(old) == 1
src = src.replace(old, new)
with open(path, "w") as fh:
    fh.write(src)
print("rail aria synced")
