"""Split the C1 collision tally per arm.

C1 is a claim about the SwarmOS arm only. The baseline StopAndWait arm is
expected to collide - that is the point of running it as a control. Summing
both arms into one counter makes C1 unfalsifiable in the wrong direction:
it reports FAIL for behaviour that is the control working as designed.
"""
import ast
import io
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "tools", "verify_criteria_powered.py")


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 match, found %d" % (label, count)
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    text = sub(text,
               "    all_coll = 0\n",
               "    base_coll = 0\n    swarm_coll = 0\n"
               "    coll_detail: list[str] = []\n",
               "counters")

    text = sub(text,
               "            all_coll += b[\"collisions\"] + s[\"collisions\"]\n",
               "            base_coll += b[\"collisions\"]\n"
               "            swarm_coll += s[\"collisions\"]\n"
               "            if s[\"collisions\"]:\n"
               "                coll_detail.append(\n"
               "                    \"%s seed=%d swarmos=%d\"\n"
               "                    % (name, seed, s[\"collisions\"]))\n",
               "accumulate")

    text = sub(text,
               "    print(\"C1 zero collisions: total=%d  %s\"\n"
               "          % (all_coll, \"PASS\" if all_coll == 0 else \"FAIL\"))\n",
               "    print(\"C1 zero collisions in the SwarmOS arm: %d  %s\"\n"
               "          % (swarm_coll, \"PASS\" if swarm_coll == 0 else \"FAIL\"))\n"
               "    print(\"   baseline arm collisions (control, expected > 0): %d\"\n"
               "          % base_coll)\n"
               "    for line in coll_detail:\n"
               "        print(\"   SwarmOS collision run: %s\" % line)\n",
               "report")

    ast.parse(text)
    io.open(PATH, "w", encoding="utf-8").write(text)
    print("patched %s" % PATH)


if __name__ == "__main__":
    main()
