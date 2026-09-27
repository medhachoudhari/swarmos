"""Fix two defects in app/sim/cosim.py found by measuring rather than reading.

1. compute_ms was read from kpis()["compute"]["last_ms"]. There is no such
   key: the engine reports "compute_ms" at the TOP level of kpis(), and the
   nested "compute" dict holds p50/p95/p99/max/samples. The .get chain
   silently produced 0.0, so every compute number the co-simulation reported
   was a fabricated zero - exactly the class of fake data the UI rules forbid.

2. p95_completion_s was absent from the delta table. It is present in kpis()
   only once a task has completed; before that compare_kpis skipped it. That
   skip is correct behaviour, but the headline set should degrade to what IS
   measurable, so the absence is now visible to the caller as a named
   missing key rather than a silently shorter list.
"""

import ast

PATH = "app/sim/cosim.py"
src = open(PATH).read()

OLD = """            compute_ms=float(data["kpis"].get("compute", {}).get("last_ms", 0.0) or 0.0),
"""
NEW = """            # Top-level "compute_ms" is this tick's measured cost. The nested
            # "compute" dict holds the distribution (p50/p95/p99/max), NOT a
            # per-tick value - reading "compute.last_ms" returned a silent 0.0.
            compute_ms=float(data["kpis"].get("compute_ms") or 0.0),
"""
assert src.count(OLD) == 1, "compute_ms anchor not unique"
src = src.replace(OLD, NEW)

OLD2 = """    out = []
    for key in keys:
        if key not in treatment or key not in baseline:
            continue
"""
NEW2 = """    out = []
    missing = []
    for key in keys:
        if key not in treatment or key not in baseline:
            # Not yet measurable in one or both arms - p95_completion_s does
            # not exist until a task has completed. Recorded by name so the
            # caller can render "--" for it rather than quietly showing a
            # shorter table that looks complete.
            missing.append(key)
            continue
"""
assert src.count(OLD2) == 1, "compare_kpis head anchor not unique"
src = src.replace(OLD2, NEW2)

OLD3 = """                better=better,
            )
        )
    return out
"""
NEW3 = """                better=better,
            )
        )
    compare_kpis.missing = tuple(missing)
    return out
"""
assert src.count(OLD3) == 1, "compare_kpis tail anchor not unique"
src = src.replace(OLD3, NEW3)

ast.parse(src)
open(PATH, "w").write(src)
print("patched %s, ast OK" % PATH)
