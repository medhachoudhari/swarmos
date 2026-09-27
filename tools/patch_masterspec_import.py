#!/usr/bin/env python3
"""Tidy the master-spec generator imports: drop the placeholder TEAL line and
the unused Pt import, and hoist the RGBColor import to the top block."""
import ast
import io

PATH = "docs/gen_master_spec_pptx.py"


def sub(text, old, new, label):
    count = text.count(old)
    assert count == 1, "%s: expected 1 occurrence, found %d" % (label, count)
    return text.replace(old, new)


src = io.open(PATH).read()

src = sub(
    src,
    "from pptx import Presentation\nfrom pptx.util import Inches, Pt\n",
    "from pptx import Presentation\nfrom pptx.dml.color import RGBColor\n"
    "from pptx.util import Inches\n",
    "import block",
)

src = sub(
    src,
    "TEAL = MEMBER_TEAL = None  # placeholder replaced below\n"
    "from pptx.dml.color import RGBColor  # noqa: E402\n\n"
    "TEAL = RGBColor(0x4F, 0xB3, 0xA6)     # sovereign\n",
    "# Two accents the team-plan deck does not define. TEAL is the sovereign\n"
    "# state colour from the UI palette, so the deck and the UI agree.\n"
    "TEAL = RGBColor(0x4F, 0xB3, 0xA6)     # sovereign\n",
    "placeholder removal",
)

ast.parse(src)
io.open(PATH, "w").write(src)
print("patched %s" % PATH)
