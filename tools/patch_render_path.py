"""Add the planned path to the per-tick render payload.

The map renderer draws each robot's remaining path, and the Decision Inspector
shows the movement intent, so both need waypoints. They were missing from
as_render_dict.

Sent as a FLAT array of rounded numbers ("p": [x0,y0,x1,y1,...]) rather than a
list of objects: at 50 robots x 10 Hz the object-per-waypoint form roughly
triples the frame size for no added information.
"""
import ast
import pathlib

p = pathlib.Path("app/sim/robot.py")
src = p.read_text()

old = """            "pc": self.spec.payload_class.value,
            "sc": self.spec.speed_class.value,
            "rogue": self.rogue,
        }"""

new = """            "pc": self.spec.payload_class.value,
            "sc": self.spec.speed_class.value,
            "rogue": self.rogue,
            # Remaining path as a flat coordinate array, and the committed
            # goal. Flat because an object per waypoint roughly triples the
            # frame at 50 robots x 10 Hz for no extra information.
            "p": [round(c, 2) for wp in self.path for c in wp],
            "tg": ([round(self.target[0], 2), round(self.target[1], 2)]
                   if self.target is not None else None),
            "pv": self.path_version,
        }"""

if new in src:
    print("already applied")
else:
    assert old in src, "anchor not found in as_render_dict"
    src = src.replace(old, new, 1)
    ast.parse(src)
    p.write_text(src)
    print("patched app/sim/robot.py as_render_dict")
