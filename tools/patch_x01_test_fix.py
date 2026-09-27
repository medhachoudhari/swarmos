"""X-01 fix. Remove the `ticks` name collision in tests/test_sovereign.py.

The helper's run length and the COMM_BLACKOUT fault's own duration were both
called `ticks`, so **params forwarding raised TypeError. Fault parameters now
travel in an explicit dict, which also makes the call sites read as what they
are: a run length, and a fault configuration.
"""
import ast
import pathlib

P = pathlib.Path("tests/test_sovereign.py")
t = P.read_text()


def sub(text, old, new, label, expect=1):
    n = text.count(old)
    assert n == expect, f"{label}: expected {expect} matches, found {n}"
    return text.replace(old, new)


t = sub(
    t,
    'def _run(ticks, *, policy=None, seed=11, inject_at=None, fault=None, **params):',
    'def _run(n_ticks, *, policy=None, seed=11, inject_at=None, fault=None, params=None):',
    "signature",
)
t = sub(t, '    for _ in range(ticks):', '    for _ in range(n_ticks):', "loop")
t = sub(
    t,
    '            eng.inject(fault, **params)',
    '            eng.inject(fault, **(params or {}))',
    "inject",
)
t = sub(
    t,
    'fault=FaultKind.COMM_BLACKOUT, robot_id="R001", ticks=400,',
    'fault=FaultKind.COMM_BLACKOUT, params={"robot_id": "R001", "ticks": 400},',
    "long blackout call sites",
    expect=6,
)
t = sub(
    t,
    '''        60, inject_at=2, fault=FaultKind.COMM_BLACKOUT,
        robot_id="R001", ticks=20,''',
    '''        60, inject_at=2, fault=FaultKind.COMM_BLACKOUT,
        params={"robot_id": "R001", "ticks": 20},''',
    "short blackout call site",
)

ast.parse(t)
P.write_text(t)
print("patched")
