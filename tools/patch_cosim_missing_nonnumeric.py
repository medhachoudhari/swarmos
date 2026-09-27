"""Record a present-but-None KPI as missing, not as silently absent.

Measured gap: at 0 completions the engine emits "p95_completion_s" as a key
whose value is None. It therefore passed the `key not in` test and was dropped
by the isinstance check instead, which did not record it - so compare_kpis.missing
came back empty while the delta table was quietly one row short. Both paths now
record the key, because the UI's promise is that an unmeasurable value renders
as "--" rather than vanishing.
"""

import ast

PATH = "app/sim/cosim.py"
src = open(PATH).read()

OLD = """        if not isinstance(t_val, (int, float)) or not isinstance(b_val, (int, float)):
            continue
"""
NEW = """        if not isinstance(t_val, (int, float)) or not isinstance(b_val, (int, float)):
            # Present but not a number - the engine reports p95_completion_s as
            # None until a task completes. Same meaning as absent, so it is
            # recorded the same way: unmeasurable, render "--".
            missing.append(key)
            continue
"""
assert src.count(OLD) == 1, "isinstance guard anchor not unique"
src = src.replace(OLD, NEW)
ast.parse(src)
open(PATH, "w").write(src)
print("patched, ast OK")
