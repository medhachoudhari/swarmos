"""Block A CSS: the banner never covers content, and the shell survives 900px.

The banner was position:fixed at the topbar height. Fixed elements reserve no
space, so at narrow widths it painted straight over the rail tab bar - the
operator could read "open the Lab tab" and then not be able to reach the Lab
tab. It is now a normal block above .shell, and .shell is sized with a dynamic
viewport height minus the banner's own height, so the geometry stays exact.
"""

import ast

ROOT = "/home/fdipglob_ai_tools/nxp60742/acc_id_work/chin_20260920"


def edit(path, pairs):
    full = ROOT + "/" + path
    with open(full) as fh:
        src = fh.read()
    for old, new in pairs:
        n = src.count(old)
        assert n == 1, "expected 1 match in %s, found %d for:\n%s" % (path, n, old[:200])
        src = src.replace(old, new)
    if path.endswith(".py"):
        ast.parse(src)
    with open(full, "w") as fh:
        fh.write(src)
    print("patched", path)


edit("web/styles/shell.css", [
    # ---- 1. banner leaves position:fixed and joins the document flow --------
    (
        """.banner {
  position: fixed;
  top: var(--shell-topbar-h);
  left: 0;
  right: 0;
  display: none;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-body);
  z-index: var(--z-banner);
  border-bottom: 1px solid var(--line-default);
}
.banner[data-visible="true"] { display: flex; }""",
        """/* IN FLOW, deliberately. A fixed banner reserves no space, so at narrow
 * widths it painted over the topbar and over the rail tab bar - it hid the
 * control its own text told the operator to press. Being a normal block above
 * .shell, it can only ever push content down, never cover it. */
.banner {
  position: relative;
  display: none;
  flex-wrap: wrap;            /* cause and action stack rather than collide */
  align-items: center;
  gap: var(--space-2) var(--space-3);
  padding: var(--space-2) var(--space-4);
  font-size: var(--text-body);
  z-index: var(--z-banner);
  border-bottom: 1px solid var(--line-default);
}
.banner[data-visible="true"] { display: flex; }
.banner__cause,
.banner__action { min-width: 0; }
/* The spacer collapses when the row has wrapped, so the dismiss button stays
 * reachable at every width instead of being pushed off the line. */
.banner .strip__spacer { flex: 1 1 var(--space-4); }""",
    ),

    # ---- 2. shell height accounts for the in-flow banner -------------------
    (
        """.shell {
  display: grid;
  height: 100vh;""",
        """.shell {
  display: grid;
  /* The banner is in flow above us, so claim the remaining height rather than
   * the whole viewport - otherwise the telemetry strip would be pushed off. */
  height: 100vh;
  height: 100dvh;
  flex: 1 1 auto;
  min-height: 0;""",
    ),

    # ---- 3. body becomes the column that owns banner + shell --------------
    (
        """html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  overflow: hidden;            /* the shell never scrolls; panels do */""",
        """html,
body {
  margin: 0;
  padding: 0;
  height: 100%;
  /* Column, so the in-flow banner and the shell share the viewport instead of
   * overlapping. The shell still never scrolls; only panels do. */
  display: flex;
  flex-direction: column;
  overflow: hidden;""",
    ),

    # ---- 4. idle link dot: neutral ink, saturation is for trouble only ----
    (
        """.link-dot[data-link="live"]    { background: var(--state-available); }""",
        """/* Idle is a legitimate, uninteresting state: connected, no run yet. It gets
 * tertiary ink because saturated colour is reserved for real conditions. */
.link-dot[data-link="idle"]    { background: var(--ink-tertiary); }
.link-dot[data-link="live"]    { background: var(--state-available); }""",
    ),

    # ---- 5. rail drawer sits under the shell, and gains a visible handle --
    (
        """  .rail {
    position: fixed;
    top: var(--shell-topbar-h);
    right: 0;
    bottom: 0;
    width: var(--rail-min-w);""",
        """  /* The drawer handle only exists where the drawer does. */
  .rail-toggle { display: inline-flex; }
  .rail {
    position: absolute;
    top: var(--shell-topbar-h);
    right: 0;
    bottom: 0;
    width: min(var(--rail-min-w), 92vw);""",
    ),

    # ---- 6. empty-state CTA, and a 900px stacking breakpoint --------------
    (
        """.empty__action {
  font-size: var(--text-label);
  color: var(--ink-tertiary);
}""",
        """.empty__action {
  font-size: var(--text-label);
  color: var(--ink-tertiary);
}
/* The empty state can PERFORM the action it names. */
.empty__cta {
  margin-top: var(--space-4);
  display: flex;
  justify-content: center;
}
.empty__hint {
  margin-top: var(--space-2);
  font-family: var(--font-mono);
  font-size: var(--text-micro);
  color: var(--ink-tertiary);
}

/* The handle is hidden at desktop widths, where the rail is a real column and
 * there is nothing to toggle. The sub-1280px block above re-enables it. */
.rail-toggle { display: none; }

/* Below 900px the telemetry strip cannot hold four metrics on one line, so it
 * scrolls horizontally rather than silently truncating a number. A clipped
 * digit is worse than a scrollbar. */
@media (max-width: 900px) {
  .shell {
    grid-template-rows: var(--shell-topbar-h) 1fr minmax(var(--bottom-min-h), 14%);
  }
  .strip {
    overflow-x: auto;
    gap: var(--space-4);
  }
  .status-cluster { gap: var(--space-3); }
  .brand__sub { display: none; }
}""",
    ),
])

print("css patched")
