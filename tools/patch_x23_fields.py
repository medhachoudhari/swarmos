"""Fix the FailureEvent field names in tests/test_x23_x24_x25.py.

The real dataclass (app/coordination/radio.py:413) names the two health fields
`previous` and `current`, not `from_health` / `to_health`. This corrects the
test to the actual contract rather than renaming the production field, because
`previous`/`current` is what FailureEvent.as_dict() already publishes to the UI.
"""
import ast
import io

PATH = "tests/test_x23_x24_x25.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, f"{label}: expected 1 occurrence, found {count}"
    return text.replace(old, new)


text = io.open(PATH).read()

text = sub(
    text,
    'assert [(e.robot_id, e.to_health) for e in events] == [',
    'assert [(e.robot_id, e.current) for e in events] == [',
    "confirmed-failure event list",
)

text = sub(
    text,
    'if e.robot_id == "R001" and e.to_health is PeerHealth.ALIVE',
    'if e.robot_id == "R001" and e.current is PeerHealth.ALIVE',
    "recovery event filter",
)

text = sub(
    text,
    "(e.robot_id, e.from_health, e.to_health, e.sim_time)",
    "(e.robot_id, e.previous, e.current, e.sim_time)",
    "replay tuple",
)

ast.parse(text)
io.open(PATH, "w").write(text)
print("patched ok")
