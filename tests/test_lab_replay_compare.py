"""Lab panel determinism receipt: Compare now must compare two distinct runs.

Drives web/js/panels/lab.js under node with a stub DOM and a fake transport.
Skipped when node is not installed.
"""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = os.path.join(ROOT, "web", "js", "panels", "lab.js")

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

SCRIPT = r"""
const { LabPanel, placeCapture, canCompare, compareCaptures } = await import(process.argv[1]);

function stubEl(values) {
  const nodes = new Map();
  return {
    innerHTML: "",
    querySelector(sel) {
      if (!nodes.has(sel)) {
        nodes.set(sel, {
          disabled: false, textContent: "", innerHTML: "", value: values[sel] ?? "",
          addEventListener(_t, fn) { this.fn = fn; },
        });
      }
      return nodes.get(sel);
    },
  };
}

// Fake backend: the hash is a pure function of config and tick, as the engine's is.
function fakeTransport() {
  const t = { cfg: null, tick: 0 };
  t.scenarios = async () => ({ ok: true, data: { scenarios: [] } });
  t.startRun = async (cfg) => { t.cfg = { ...cfg, policy: "swarmos" }; t.tick = 0; return { ok: true, data: {} }; };
  t.traceHash = async () => ({
    ok: true,
    data: { hash: `s${t.cfg.seed}f${t.cfg.fleet_size}t${t.tick}`, tick: t.tick, config: t.cfg },
  });
  return t;
}

const out = {};
const el = stubEl({ "#lab-scenario": "rush_50", "#lab-fleet": "8", "#lab-seed": "11", "#lab-integrity": "off" });
const tr = fakeTransport();
const p = new LabPanel(el, tr);
await p.init();
const $ = (s) => el.querySelector(s);
const click = async (s) => { await $(s).fn(); };
const text = () => $("#lab-hashes").innerHTML.replace(/\s+/g, " ");

// Run 1, captured at tick 1000.
await click("#lab-start");
tr.tick = 1000;
await click("#lab-capture");
out.one_capture_compare_disabled = $("#lab-compare").disabled;
await click("#lab-compare");                 // forced click on the same run
out.one_capture_result = p.result;
await click("#lab-capture");                 // capturing again on Run 1 only replaces the baseline
out.recapture_same_run_rerun = p.rerun;
out.recapture_compare_disabled = $("#lab-compare").disabled;
const run1 = p.baseline.hash;

// Run 2 with the same config: Start must not erase Run 1.
await click("#lab-start");
out.after_start_baseline = p.baseline && p.baseline.hash;
out.after_start_text_has_run1 = text().includes(run1);
out.after_start_compare_disabled = $("#lab-compare").disabled;
tr.tick = 995;
await click("#lab-capture");
out.wrong_tick_compare_disabled = $("#lab-compare").disabled;
tr.tick = 1000;
await click("#lab-capture");
out.run2_compare_enabled = !$("#lab-compare").disabled;
await click("#lab-compare");
out.same_result = p.result;
out.same_text = text();

// Run 3 with seed 12 against the same Run 1 baseline.
$("#lab-seed").value = "12";
await click("#lab-start");
tr.tick = 1000;
await click("#lab-capture");
await click("#lab-compare");
out.seed12_result = p.result;
out.seed12_text = text();

// Pure helpers: a capture can never be compared with its own run.
const a = { hash: "x", tick: 5, run: 1 };
out.self_place = placeCapture(a, { hash: "x", tick: 5, run: 1 }).rerun;
out.self_can = canCompare(a, { hash: "x", tick: 5, run: 1 });
out.self_cmp = compareCaptures(a, a);

console.log(JSON.stringify(out));
"""


def _run():
    res = subprocess.run(
        [NODE, "--input-type=module", "-e", SCRIPT, LAB],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def flow():
    return _run()


def test_one_capture_alone_cannot_produce_a_comparison(flow):
    assert flow["one_capture_compare_disabled"] is True
    assert flow["one_capture_result"] is None
    assert flow["recapture_same_run_rerun"] is None
    assert flow["recapture_compare_disabled"] is True


def test_run1_capture_survives_start_of_run2(flow):
    assert flow["after_start_baseline"] == "s11f8t1000"
    assert flow["after_start_text_has_run1"] is True
    assert flow["after_start_compare_disabled"] is True


def test_run2_capture_at_same_tick_enables_compare(flow):
    assert flow["wrong_tick_compare_disabled"] is True
    assert flow["run2_compare_enabled"] is True


def test_identical_runs_report_identical_pass(flow):
    assert flow["same_result"] == "identical"
    assert "IDENTICAL - PASS" in flow["same_text"]


def test_different_seed_reports_mismatch(flow):
    assert flow["seed12_result"] == "mismatch"
    assert "MISMATCH" in flow["seed12_text"]
    assert "IDENTICAL" not in flow["seed12_text"]


def test_self_comparison_is_impossible(flow):
    assert flow["self_place"] is None
    assert flow["self_can"] is False
    assert flow["self_cmp"] is None
