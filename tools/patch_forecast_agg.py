"""Seeds with zero scoreable pairs must be skipped in the weighted mean, not
multiplied by None. A seed that produced no prediction is not evidence of a
zero error; it is simply absent from the sample.
"""
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
    "    m = sum(r[\"model_mae\"] * r[\"samples\"] for r in rows) / tot\n"
    "    p = sum(r[\"pers_mae\"] * r[\"samples\"] for r in rows) / tot\n",
    "    scored = [r for r in rows if r[\"samples\"] > 0]\n"
    "    m = sum(r[\"model_mae\"] * r[\"samples\"] for r in scored) / tot\n"
    "    p = sum(r[\"pers_mae\"] * r[\"samples\"] for r in scored) / tot\n",
    "weighted mean guard",
)
ast.parse(text)
io.open(PATH, "w", encoding="utf-8").write(text)
print("patched", PATH)
