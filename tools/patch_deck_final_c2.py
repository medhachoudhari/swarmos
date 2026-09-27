"""Move slide 18's C2 figures onto the final post-defect-2 measurement.

The -13.7 pct / [-26.6, -0.7] pair came from the post-defect-1 log. The run that
now backs the document is reports/criteria_after_envelope_fix.log: -19.3 pct,
95 pct CI [-36.0, -2.6]. Character budget per slide stays under 1400.
"""
import ast
import io
import sys

SRC = "docs/gen_master_spec_pptx.py"


def sub(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 match, found %d" % (label, n)
    return text.replace(old, new)


def main():
    text = io.open(SRC, encoding="utf-8").read()
    text = sub(
        text,
        '        ("-13.7 pct", "C2 mean, sign negative", BAD),',
        '        ("-19.3 pct", "C2 mean, sign negative", BAD),',
        "kpi card",
    )
    text = sub(
        text,
        '        "C2: NOT MET. Mean -13.7 percent, 95 percent CI [-26.6, -0.7]. The whole "\n'
        '        "interval is below zero, so on this statistic we are slower.",',
        '        "C2: NOT MET. Mean -19.3 percent, 95 percent CI [-36.0, -2.6]. It got "\n'
        '        "worse when we fixed defect 2, which is the right direction: a sound "\n'
        '        "step bound withholds speed the arbiter used to grant.",',
        "C2 bullet",
    )
    ast.parse(text)
    io.open(SRC, "w", encoding="utf-8").write(text)
    print("patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
