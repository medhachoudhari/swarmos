"""Fix the SimEngine construction in tools/measure_forecast.py.

SimEngine has no fleet_size kwarg; the scenario carries the fleet size, so a
ScenarioSpec must be built and passed positionally, exactly as
tools/measure_fix.py:27 already does.
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
    "from app.coordination.swarm_policy import SwarmPolicy\n"
    "from app.ml.forecast import Forecaster, zone_of\n"
    "from app.sim.engine import SimEngine\n",
    "import dataclasses\n"
    "\n"
    "sys.path.insert(0, \".\")\n"
    "\n"
    "from app.api.runner import _make_policy\n"
    "from app.ml.forecast import Forecaster, zone_of\n"
    "from app.sim.engine import SimEngine\n"
    "from app.sim.scenarios import SCENARIOS\n",
    "imports",
)

text = sub(
    text,
    "        eng = SimEngine(seed=seed, policy=SwarmPolicy(), fleet_size=fleet,\n"
    "                        scenario=\"rush_50\")\n",
    "        scen = SCENARIOS[\"rush_50\"]\n"
    "        if fleet and fleet != scen.fleet_size:\n"
    "            scen = dataclasses.replace(scen, fleet_size=fleet)\n"
    "        eng = SimEngine(scen, seed=seed,\n"
    "                        policy=_make_policy(\"swarmos\", seed),\n"
    "                        label=\"swarmos\")\n",
    "constructor",
)

ast.parse(text)
io.open(PATH, "w", encoding="utf-8").write(text)
print("patched", PATH)
