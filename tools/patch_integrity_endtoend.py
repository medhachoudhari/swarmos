"""Close the integrity switch end to end.

The previous patch added `integrity` to RunConfig and a parameter to
_make_policy, but the single call site still built the policy without it. A
switch wired at one end only is worse than no switch: the operator would arm
the sentinel council, see nothing happen, and have no way to tell whether the
feature or the fleet was at fault. Three edits close the loop:

  POST body -> RunConfig.integrity -> _make_policy(..., integrity=...)
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def patch(rel, pairs):
    path = ROOT / rel
    src = path.read_text()
    for old, new in pairs:
        assert src.count(old) == 1, (rel, old[:70], src.count(old))
        src = src.replace(old, new)
    ast.parse(src)
    path.write_text(src)
    print("patched", rel)


patch("app/api/runner.py", [(
    """                policy=_make_policy(cfg.policy, cfg.seed),""",
    """                policy=_make_policy(cfg.policy, cfg.seed,
                                    integrity=cfg.integrity),""",
)])

patch("app/api/server.py", [(
    """    POST /api/sim/start     {scenario, seed, fleet_size, policy, speed}""",
    """    POST /api/sim/start     {scenario, seed, fleet_size, policy, speed,
                             integrity}""",
), (
    """        speed = _as_float(data, "speed", 1.0)""",
    """        speed = _as_float(data, "speed", 1.0)
        # Off unless asked for: the integrity layer changes nothing when off,
        # which is what keeps every previously recorded trace hash valid.
        integrity = bool(data.get("integrity", False))""",
), (
    """        policy=policy,
        speed=speed,
    )""",
    """        policy=policy,
        speed=speed,
        integrity=integrity,
    )""",
)])
