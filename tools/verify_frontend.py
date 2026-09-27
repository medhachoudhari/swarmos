"""Static contract check for the M1 frontend.

Three things break a no-build ES-module app and none of them are caught by a
syntax check:
  1. a DOM id referenced in JS that does not exist in index.html
  2. an imported symbol that the source module never exports
  3. a method called on a class instance that the class does not define

This script checks all three by text analysis. It is not a type checker; it is
a smoke test that would have caught every wiring mistake made so far.
"""
import re
import sys
from pathlib import Path

WEB = Path("web")
html = (WEB / "index.html").read_text()
html_ids = set(re.findall(r'id="([^"]+)"', html))

js_files = sorted(WEB.glob("js/**/*.js"))
sources = {p: p.read_text() for p in js_files}

errors, warnings = [], []

# --- 1. DOM ids -----------------------------------------------------------
for p, src in sources.items():
    for m in re.finditer(r'getElementById\("([^"]+)"\)|\$\("([^"]+)"\)', src):
        rid = m.group(1) or m.group(2)
        if rid not in html_ids:
            errors.append(f"{p}: DOM id '{rid}' not present in index.html")

# --- 2. imports vs exports ----------------------------------------------
exports = {}
for p, src in sources.items():
    names = set()
    for m in re.finditer(r'export\s+(?:class|const|function)\s+(\w+)', src):
        names.add(m.group(1))
    for m in re.finditer(r'export\s*\{([^}]*)\}', src):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                names.add(part.split()[-1])
    exports[p.name] = names

for p, src in sources.items():
    for m in re.finditer(r'import\s*\{([^}]*)\}\s*from\s*"([^"]+)"', src):
        wanted = [x.strip().split()[-1] for x in m.group(1).split(",") if x.strip()]
        target = (p.parent / m.group(2)).resolve()
        if not target.exists():
            errors.append(f"{p}: import target {m.group(2)} does not exist")
            continue
        have = exports.get(target.name, set())
        for w in wanted:
            if w not in have:
                errors.append(f"{p}: imports '{w}' from {target.name} which does not export it")

# --- 3. methods called on known instances -------------------------------
def methods_of(src, cls):
    body = src.split(f"class {cls}", 1)
    if len(body) < 2:
        return set()
    return set(re.findall(r'^\s{2}(?:async\s+)?(\w+)\s*\(', body[1], re.M))

def fields_of(src, cls):
    body = src.split(f"class {cls}", 1)
    if len(body) < 2:
        return set()
    return set(re.findall(r'this\.(\w+)\s*=', body[1]))

main_raw = sources[WEB / "js" / "main.js"]
main = "\n".join(l for l in main_raw.splitlines() if not l.lstrip().startswith("import "))
targets = {
    "map": ("map.js", "MapView"),
    "transport": ("transport.js", "Transport"),
}
for var, (fname, cls) in targets.items():
    path = WEB / "js" / fname
    api = methods_of(sources[path], cls) | fields_of(sources[path], cls)
    for m in re.finditer(rf'\b{var}\.(\w+)', main):
        name = m.group(1)
        if name not in api:
            errors.append(f"main.js: {var}.{name} is not defined on {cls} ({fname})")

# panels must all expose render()
for fname, cls in (("fleet.js", "FleetPanel"), ("inspector.js", "InspectorPanel"),
                   ("lab.js", "LabPanel"), ("analytics.js", "AnalyticsPanel")):
    path = WEB / "js" / "panels" / fname
    if "render" not in methods_of(sources[path], cls):
        errors.append(f"{fname}: {cls} has no render() method")

# --- 4. css custom properties actually defined --------------------------
tokens = (WEB / "styles" / "tokens.css").read_text()
defined = set(re.findall(r'(--[\w-]+)\s*:', tokens))
for p, src in list(sources.items()) + [(WEB / "styles" / "panels.css", (WEB / "styles" / "panels.css").read_text()),
                                       (WEB / "styles" / "shell.css", (WEB / "styles" / "shell.css").read_text())]:
    for m in re.finditer(r'var\((--[\w-]+)\s*[,)]', src):
        if m.group(1) not in defined:
            warnings.append(f"{p}: var({m.group(1)}) is not defined in tokens.css")
    for m in re.finditer(r'css\("(--[\w-]+)"\)', src):
        if m.group(1) not in defined:
            warnings.append(f"{p}: css('{m.group(1)}') is not defined in tokens.css")

print(f"checked {len(sources)} js files, {len(html_ids)} html ids, {len(defined)} tokens")
for w in sorted(set(warnings)):
    print("WARN ", w)
for e in sorted(set(errors)):
    print("ERROR", e)
print(f"\n{len(set(errors))} errors, {len(set(warnings))} warnings")
sys.exit(1 if errors else 0)
