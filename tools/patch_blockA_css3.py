"""The rail drawer is now position:absolute, which needs a positioned ancestor.
Without one it would resolve against the viewport and so ignore the in-flow
banner above the shell, re-creating the overlap this whole block removes.
Making .shell the containing block keeps the drawer inside the shell at every
banner height. z-index is left to the existing --z-rail token.
"""

ROOT = "/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920"
path = ROOT + "/web/styles/shell.css"
with open(path) as fh:
    src = fh.read()

old = """.shell {
  display: grid;"""
new = """.shell {
  display: grid;
  /* Containing block for the sub-1280px rail drawer, so the drawer is measured
   * from the shell and not from the viewport. */
  position: relative;"""
assert src.count(old) == 1
src = src.replace(old, new)

with open(path, "w") as fh:
    fh.write(src)
print("shell is now the containing block")
