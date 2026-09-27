"""SimRobot.position is a plain (x, y) tuple, not a vector object."""
import ast
import io

PATH = "tools/measure_forecast.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, f"{label}: expected 1 match, found {count}"
    return text.replace(old, new)


text = io.open(PATH, encoding="utf-8").read()
text = sub(
    text,
    "                z = zone_of(r.position.x, r.position.y)\n",
    "                px, py = r.position\n"
    "                z = zone_of(px, py)\n",
    "position unpack",
)
ast.parse(text)
io.open(PATH, "w", encoding="utf-8").write(text)
print("patched", PATH)
