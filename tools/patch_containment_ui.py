"""Make containment visible: wire the spoofed claim and the integrity flag.

Three edits:

1. web/js/store.js - adaptRobot carries the compact "cl" key (the position a
   rogue robot CLAIMS to be at) into a canonical `claimed` field. store.js is
   the single wire-format boundary, so this is the only place it may happen.
2. web/js/map.js - draw the claim as a hollow ghost ring joined to the true
   body by a dashed line. This is the one picture that explains the whole
   mechanism without a word of narration: the fleet saw two positions for one
   robot and believed its neighbours rather than the robot.
3. app/api/runner.py - expose `integrity` on RunConfig so the operator can
   arm the sentinel council before injecting the rogue. Default False, so
   every previously recorded trace hash stays valid.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def patch(rel, pairs, *, py=False):
    path = ROOT / rel
    src = path.read_text()
    for old, new in pairs:
        assert src.count(old) == 1, (rel, old[:60], src.count(old))
        src = src.replace(old, new)
    if py:
        ast.parse(src)
    path.write_text(src)
    print("patched", rel)


# -- 1. the wire boundary -------------------------------------------------
patch("web/js/store.js", [(
    """    rogue: Boolean(w.rogue),""",
    """    rogue: Boolean(w.rogue),
    // Where the robot SAYS it is, when that differs from where it is. Null
    // for every honest robot, which is almost all of them - so the map can
    // treat a non-null value as the whole story on its own.
    claimed: Array.isArray(w.cl) ? { x: w.cl[0], y: w.cl[1] } : null,""",
)])

# -- 2. the picture -------------------------------------------------------
patch("web/js/map.js", [(
    """      // Heading wedge. Only when moving -- a heading on a stopped robot is""",
    """      // The lie, drawn. A rogue robot's claimed position is shown as a
      // hollow ring tied to its real body by a dashed line: the gap IS the
      // evidence, and its length is the error the quorum voted on.
      if (r.claimed) {
        const [cx, cy] = this.toScreen(r.claimed.x, r.claimed.y);
        ctx.strokeStyle = STATE_COLOR.QUARANTINED || color;
        ctx.globalAlpha = 0.75;
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(cx, cy);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.arc(cx, cy, rpx, 0, Math.PI * 2);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Heading wedge. Only when moving -- a heading on a stopped robot is""",
)])

# -- 3. the switch --------------------------------------------------------
patch("app/api/runner.py", [(
    """def _make_policy(name: str, seed: int):""",
    """def _make_policy(name: str, seed: int, integrity: bool = False):""",
), (
    """        return tuned()
    return SwarmPolicy()""",
    """        # The baseline has no integrity layer by design: being defenceless
        # against a lying robot is part of what the comparison measures.
        return tuned()
    return SwarmPolicy(integrity=integrity)""",
), (
    """    policy: str = "swarmos"
    speed: float = 1.0""",
    """    policy: str = "swarmos"
    speed: float = 1.0
    integrity: bool = False""",
), (
    """            speed=max(0.1, min(10.0, float(self.speed))),
        )""",
    """            speed=max(0.1, min(10.0, float(self.speed))),
            integrity=bool(self.integrity),
        )""",
), (
    """            "speed": self.speed,
        }""",
    """            "speed": self.speed,
            "integrity": self.integrity,
        }""",
)], py=True)
