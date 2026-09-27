"""One-shot fix for the missing-KPI test in tests/test_cosim.py.

The original assertion was wrong, not the product: an empty baseline dict
means BOTH keys are missing, so compare_kpis correctly returns nothing. The
real contract to pin is asymmetry - a key present in the treatment arm but
absent from the baseline arm must be dropped, while the keys present in both
survive.
"""

import ast
import pathlib

PATH = pathlib.Path("tests/test_cosim.py")

OLD = '''    deltas = compare_kpis(
        {"tasks_complete": 10.0},
        {},
        keys=("tasks_complete", "collisions"),
    )
    keys = [d.key for d in deltas]
    assert "tasks_complete" in keys
    assert "collisions" not in keys
'''

NEW = '''    deltas = compare_kpis(
        {"tasks_complete": 10.0, "collisions": 0.0},
        {"tasks_complete": 8.0},
        keys=("tasks_complete", "collisions"),
    )
    keys = [d.key for d in deltas]
    # Present in both arms, so it is comparable and must appear.
    assert "tasks_complete" in keys
    # Present in one arm only. There is no honest delta, so it is dropped
    # rather than silently compared against an invented zero.
    assert "collisions" not in keys

    # And when NEITHER arm has the key, nothing is invented either.
    assert compare_kpis({}, {}, keys=("collisions",)) == []
'''

src = PATH.read_text()
assert src.count(OLD) == 1, "anchor not unique"
src = src.replace(OLD, NEW)
ast.parse(src)
PATH.write_text(src)
print("patched tests/test_cosim.py")
