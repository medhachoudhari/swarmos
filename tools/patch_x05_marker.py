"""Record the X-05 measurement at the construction site of the forecaster.

Anyone tempted to wire this model into the planner should hit the number on
their way past, not have to find a document.
"""
import ast
import io

PATH = "app/sim/engine.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, f"{label}: expected 1 match, found {count}"
    return text.replace(old, new)


text = io.open(PATH, encoding="utf-8").read()
text = sub(
    text,
    "        # trace hash. tests/test_ml.py proves that rather than asserting it.\n"
    "        self.forecaster = Forecaster()\n",
    "        # trace hash. tests/test_ml.py proves that rather than asserting it.\n"
    "        #\n"
    "        # X-05, measured 2026-09-21, do NOT promote this into the planner.\n"
    "        # Scored against a persistence baseline on identical (zone, target\n"
    "        # tick) pairs by tools/measure_forecast.py, 1800 ticks, seeds\n"
    "        # 11/13/17, rush_50:\n"
    "        #   fleet  8: model MAE 5.344 vs persistence 0.667 (701 pct worse)\n"
    "        #   fleet 50: model MAE 2.308 vs persistence 0.415 (456 pct worse)\n"
    "        # A linear slope over a 20 tick horizon overshoots because robot\n"
    "        # flow is bursty, not linear. It loses to guessing 'the zone holds\n"
    "        # what it holds now', so it may not steer routing. The fence is\n"
    "        # enforced by tests/test_ml_fence.py; reasoning in\n"
    "        # docs/X05_FORECASTER_DECISION.md.\n"
    "        self.forecaster = Forecaster()\n",
    "x05 marker",
)
ast.parse(text)
io.open(PATH, "w", encoding="utf-8").write(text)
print("patched", PATH)
