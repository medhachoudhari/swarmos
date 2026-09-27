"""Cascade order fix. The base .rail-toggle{display:none} is declared later in
the file than the sub-1280px media query, and at equal specificity the later
rule wins - so the drawer handle would have stayed hidden at exactly the widths
that need it. Raising the media-query selector to .topbar .rail-toggle makes it
win on specificity, which is order independent.
"""

ROOT = "/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920"
path = ROOT + "/web/styles/shell.css"
with open(path) as fh:
    src = fh.read()

old = "  .rail-toggle { display: inline-flex; }"
new = "  .topbar .rail-toggle { display: inline-flex; }"
assert src.count(old) == 1
src = src.replace(old, new)

with open(path, "w") as fh:
    fh.write(src)
print("cascade fixed")
