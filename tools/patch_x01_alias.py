"""Separate the two network faults the operator can ask for.

Before this patch the Lab's 'comm_blackout' alias resolved to LINK_IMPAIR,
which degrades every link (10 pct drops plus latency) and proves X-02. That is
a real and useful fault, but it is NOT the X-01 fault, and with the alias
pointing at it the new COMM_BLACKOUT handler was unreachable from the UI.

So: 'link_impair' keeps LINK_IMPAIR, and 'comm_blackout' now means what its
name says - cut ONE robot's radio. Two names, two faults, no overloading.
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, f"{label}: expected 1 match, found {count}"
    return text.replace(old, new)


def runner(s):
    return sub(
        s,
        '    "comm_blackout": "LINK_IMPAIR",\n',
        '    "comm_blackout": "COMM_BLACKOUT",\n'
        '    "link_impair": "LINK_IMPAIR",\n',
        "runner: alias split",
    )


def lab(s):
    return sub(
        s,
        '  { id: "comm_blackout", label: "Comm blackout (cut one robot\'s radio 6 s)" },\n',
        '  { id: "comm_blackout", label: "Comm blackout (cut one robot\'s radio 6 s)" },\n'
        '  { id: "link_impair", label: "Link impairment (drops and latency, fleet-wide)" },\n',
        "lab: add link_impair option",
    )


def main():
    p = ROOT / "app/api/runner.py"
    out = runner(p.read_text())
    ast.parse(out)
    p.write_text(out)
    print("patched app/api/runner.py")

    p = ROOT / "web/js/panels/lab.js"
    p.write_text(lab(p.read_text()))
    print("patched web/js/panels/lab.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
