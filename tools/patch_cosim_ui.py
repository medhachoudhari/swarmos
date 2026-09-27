"""Wire the Compare panel into the shell: markup, styles, bootstrap.

Three files, one script, because the tab button, the tab panel and the panel
object must appear together or the rail renders a tab that opens nothing.
"""
import subprocess
import sys


def sub(path_text, old, new, label):
    n = path_text.count(old)
    assert n == 1, f"{label}: expected 1 match, found {n}"
    return path_text.replace(old, new)


# ------------------------------------------------------------------- html ---

HTML = "web/index.html"
html = open(HTML).read()

html = sub(
    html,
    '      <button class="rail__tab" role="tab" id="tab-analytics" aria-selected="false" aria-controls="panel-analytics">Analytics</button>\n',
    '      <button class="rail__tab" role="tab" id="tab-cosim"     aria-selected="false" aria-controls="panel-cosim">Compare</button>\n'
    '      <button class="rail__tab" role="tab" id="tab-analytics" aria-selected="false" aria-controls="panel-analytics">Analytics</button>\n',
    "tab button",
)

html = sub(
    html,
    '      <section class="panel" role="tabpanel" id="panel-analytics" aria-labelledby="tab-analytics" data-active="false"></section>\n',
    '      <section class="panel" role="tabpanel" id="panel-cosim"     aria-labelledby="tab-cosim"     data-active="false"></section>\n'
    '      <section class="panel" role="tabpanel" id="panel-analytics" aria-labelledby="tab-analytics" data-active="false"></section>\n',
    "tab panel",
)

open(HTML, "w").write(html)

# -------------------------------------------------------------------- css ---

CSS = "web/styles/panels.css"
css = open(CSS).read()

css += """
/* --------------------------------------------------- X-12 compare panel --- */

/* The delta strip. Four columns: metric, treatment, baseline, delta. A fixed
 * grid rather than a table so the numbers line up on their digits even as rows
 * are replaced at 10 Hz. */
.delta {
  margin-top: var(--space-4);
  border-top: 1px solid var(--line-subtle);
}
.delta__head,
.delta__row {
  display: grid;
  grid-template-columns: 1.4fr 0.9fr 0.9fr 1.1fr;
  gap: var(--space-2);
  align-items: baseline;
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line-subtle);
}
.delta__head {
  font-size: var(--text-label);
  letter-spacing: var(--tracking-label);
  text-transform: uppercase;
  color: var(--ink-tertiary);
}
.delta__row {
  border-left: 2px solid transparent;
  padding-left: var(--space-2);
  transition: border-color var(--dur-base) var(--ease-out);
}
.delta__metric {
  font-size: var(--text-body);
  color: var(--ink-secondary);
}
.delta__val {
  font-size: var(--text-body);
  color: var(--ink-primary);
  text-align: right;
}
/* The baseline column is context, not the subject, so it sits one ink level
 * back. The eye should land on the treatment column first. */
.delta__val--base { color: var(--ink-secondary); }
.delta__delta { color: var(--ink-secondary); }

/* Saturated colour marks the winning arm and nothing else. A tie is ink:
 * colouring a tie green would be a claim the data does not support. */
.delta__row[data-won="swarmos"] { border-left-color: var(--state-available); }
.delta__row[data-won="swarmos"] .delta__delta { color: var(--ink-primary); }
.delta__row[data-won="baseline"] { border-left-color: var(--state-waiting); }
.delta__row[data-won="baseline"] .delta__delta { color: var(--state-waiting); }
.delta__row[data-won="tie"] .delta__delta { color: var(--ink-tertiary); }

.cosim-status { margin-top: var(--space-4); }

/* An inline note, never a toast. A problem with the comparison belongs next to
 * the comparison. */
.cosim-note {
  margin-top: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-left: 2px solid var(--line-strong);
  border-radius: var(--radius-sm);
  font-size: var(--text-body);
  color: var(--ink-secondary);
  background: var(--surface-2);
}
.cosim-note[data-tone="bad"] {
  border-left-color: var(--state-blocked);
  background: var(--state-blocked-wash);
  color: var(--ink-primary);
}

/* Four fault buttons do not fit on one line in a 320 px rail. */
.btn-row--wrap { flex-wrap: wrap; }
.btn-row--wrap .btn { flex: 1 1 45%; }
"""
open(CSS, "w").write(css)

# --------------------------------------------------------------- main.js ---

MAIN = "web/js/main.js"
main = open(MAIN).read()

main = sub(
    main,
    'import { AnalyticsPanel } from "./panels/analytics.js";\n',
    'import { AnalyticsPanel } from "./panels/analytics.js";\n'
    'import { CosimPanel } from "./panels/cosim.js";\n'
    'import { CosimClient } from "./cosim.js";\n',
    "main imports",
)

main = sub(
    main,
    'const map = new MapView($("map"));\n',
    'const map = new MapView($("map"));\n'
    '\n'
    '/* The co-simulation is a second, independent stream. It is constructed\n'
    ' * unconditionally but connects only when a comparison is started, so an\n'
    ' * operator who never opens the Compare tab pays nothing for it. */\n'
    'const cosim = new CosimClient(transport);\n'
    '\n'
    '/* The map asks for ghosts every animation frame; the client decides\n'
    ' * whether there are any it can honestly supply. The scenario and seed of\n'
    ' * the LIVE run are the gate: a comparison of a different warehouse must\n'
    ' * never be painted over this one. */\n'
    'map.ghostSource = () => cosim.ghostSource(store.scenario, store.seed);\n',
    "cosim client",
)

main = sub(
    main,
    '  analytics: new AnalyticsPanel($("panel-analytics")),\n',
    '  cosim: new CosimPanel($("panel-cosim"), cosim),\n'
    '  analytics: new AnalyticsPanel($("panel-analytics")),\n',
    "panel registry",
)

# The Compare panel must repaint on cosim frames, which arrive on their own
# socket and therefore do NOT go through the store subscription.
main = sub(
    main,
    'window.addEventListener("resize", () => {\n',
    'cosim.subscribe(() => {\n'
    '  if (activeTab === "cosim") panels.cosim.render();\n'
    '});\n'
    '\n'
    'window.addEventListener("resize", () => {\n',
    "cosim subscription",
)

main = sub(
    main,
    'panels.lab.init();\n',
    'panels.lab.init();\n'
    'panels.cosim.init();\n',
    "panel init",
)

open(MAIN, "w").write(main)

for path, cmd in ((MAIN, ["node", "--check", MAIN]),):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"check failed: {path}")

print("compare panel wired: index.html, panels.css, main.js")
