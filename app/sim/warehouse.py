"""
M5 Warehouse - static geometry and the ONLY grid <-> metre conversion.

Frozen convention: the canonical spatial model is continuous 2-D metres.
Coordination reasons about discrete cells for space-time reservation, so this
module owns the conversion in both directions and nothing else may duplicate it.

Layout model
------------
A warehouse is a rectangular grid of CELL_M metre cells. Cells are either
FREE aisle, RACK (permanently blocked), CHARGER, PICK station or DROP station.
Aisles run north-south between rack blocks with cross-aisles at intervals, which
is what produces the narrow-aisle contention the coordination layer must solve.

Blocked aisles (the blocked_aisle scenario and live fault injection) are held
separately in `blocked` so they can be added and removed at run time without
mutating the static layout.
"""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass, field


CELL_M = 1.0          # one grid cell is one metre square
ROBOT_RADIUS_M = 0.35  # footprint radius, used for the safety envelope


class Cell(str, enum.Enum):
    FREE = "FREE"
    RACK = "RACK"
    CHARGER = "CHARGER"
    PICK = "PICK"
    DROP = "DROP"


@dataclass(frozen=True)
class Zone:
    """A named rectangular region. Used for partition injection (X-02)."""

    name: str
    x0: int
    y0: int
    x1: int
    y1: int

    def contains(self, cx: int, cy: int) -> bool:
        return self.x0 <= cx <= self.x1 and self.y0 <= cy <= self.y1


@dataclass
class Warehouse:
    """Static warehouse geometry plus dynamic blockages.

    Coordinates: cell indices (cx, cy) are integers; metres (x, y) are floats
    measured to the CENTRE of a cell, so cell (0, 0) has centre (0.5, 0.5).
    """

    width: int
    height: int
    grid: list[list[Cell]] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    blocked: set[tuple[int, int]] = field(default_factory=set)

    # --- construction -----------------------------------------------------

    @classmethod
    def standard(cls, width: int = 60, height: int = 40,
                 aisle_period: int = 4, cross_period: int = 10,
                 aisle_width: int = 2, cross_width: int = 2) -> "Warehouse":
        """Build a realistic rack-and-aisle warehouse.

        Every aisle_period columns there is an aisle aisle_width cells wide, and
        every cross_period rows a cross aisle cross_width rows deep. Chargers sit
        along the left wall, pick stations along the bottom, drop stations along
        the top - so tasks generate genuine long traversals through contention.

        aisle_width defaults to 2 for a deliberate reason. A one-cell aisle is
        strictly single file: two robots meeting head-on in it can never pass,
        so ANY policy without joint multi-step planning gridlocks permanently,
        and the fleet's throughput becomes a property of the floor plan rather
        than of the coordination. Real distribution centres size main aisles for
        two-way AMR traffic for exactly this reason. The narrow_aisle_deadlock
        scenario sets aisle_width=1 on purpose, because there the wedge IS the
        thing being demonstrated.
        """
        grid = [[Cell.FREE for _ in range(width)] for _ in range(height)]

        for cy in range(height):
            if cy % cross_period < cross_width or cy == height - 1:
                continue                      # full cross aisle
            for cx in range(width):
                if cx < 2 or cx >= width - 2:
                    continue                  # perimeter ring aisle
                if cx % aisle_period < aisle_width:
                    continue                  # north-south aisle
                grid[cy][cx] = Cell.RACK

        # Chargers on the left wall, spaced out
        for i, cy in enumerate(range(2, height - 2, 6)):
            grid[cy][0] = Cell.CHARGER

        # Pick stations along the bottom row, drop stations along the top
        for cx in range(4, width - 4, 6):
            grid[height - 1][cx] = Cell.PICK
            grid[0][cx] = Cell.DROP

        wh = cls(width=width, height=height, grid=grid)
        wh.zones = [
            Zone("WEST", 0, 0, width // 3, height - 1),
            Zone("CENTRE", width // 3 + 1, 0, 2 * width // 3, height - 1),
            Zone("EAST", 2 * width // 3 + 1, 0, width - 1, height - 1),
        ]
        return wh

    # --- the ONE conversion -----------------------------------------------

    def cell_to_m(self, cx: int, cy: int) -> tuple[float, float]:
        """Cell index to the metre coordinate of that cell's centre."""
        return ((cx + 0.5) * CELL_M, (cy + 0.5) * CELL_M)

    def m_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """Metre coordinate to the containing cell index."""
        return (int(math.floor(x / CELL_M)), int(math.floor(y / CELL_M)))

    # --- queries ----------------------------------------------------------

    def in_bounds(self, cx: int, cy: int) -> bool:
        return 0 <= cx < self.width and 0 <= cy < self.height

    def cell_at(self, cx: int, cy: int) -> Cell | None:
        if not self.in_bounds(cx, cy):
            return None
        return self.grid[cy][cx]

    def is_navigable(self, cx: int, cy: int) -> bool:
        """True if a robot may occupy this cell right now."""
        if not self.in_bounds(cx, cy):
            return False
        if (cx, cy) in self.blocked:
            return False
        return self.grid[cy][cx] is not Cell.RACK

    def neighbours(self, cx: int, cy: int) -> list[tuple[int, int]]:
        """4-connected navigable neighbours. No diagonals: AMRs in aisles do
        not cut corners, and 4-connectivity keeps the reservation envelope
        sound."""
        out = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if self.is_navigable(nx, ny):
                out.append((nx, ny))
        return out

    def cells_of_type(self, kind: Cell) -> list[tuple[int, int]]:
        return [(cx, cy)
                for cy in range(self.height)
                for cx in range(self.width)
                if self.grid[cy][cx] is kind]

    def zone_of(self, cx: int, cy: int) -> str:
        for z in self.zones:
            if z.contains(cx, cy):
                return z.name
        return "UNZONED"

    # --- dynamic blockage (blocked_aisle scenario and fault injection) ----

    def block_cells(self, cells) -> int:
        """Block navigable cells. Returns how many were newly blocked."""
        added = 0
        for cx, cy in cells:
            if self.in_bounds(cx, cy) and (cx, cy) not in self.blocked:
                self.blocked.add((cx, cy))
                added += 1
        return added

    def clear_blockage(self) -> int:
        n = len(self.blocked)
        self.blocked.clear()
        return n

    def block_aisle_segment(self, cx: int, cy0: int, cy1: int) -> int:
        """Block a run of one aisle - the blocked_aisle injection."""
        return self.block_cells(
            (cx, cy) for cy in range(min(cy0, cy1), max(cy0, cy1) + 1))

    # --- reporting --------------------------------------------------------

    def stats(self) -> dict:
        free = sum(1 for row in self.grid for c in row if c is not Cell.RACK)
        return {
            "width": self.width,
            "height": self.height,
            "cell_m": CELL_M,
            "navigable_cells": free - len(self.blocked),
            "rack_cells": self.width * self.height - free,
            "blocked_cells": len(self.blocked),
            "chargers": len(self.cells_of_type(Cell.CHARGER)),
            "pick_stations": len(self.cells_of_type(Cell.PICK)),
            "drop_stations": len(self.cells_of_type(Cell.DROP)),
            "zones": [z.name for z in self.zones],
        }

    def to_render_payload(self) -> dict:
        """Compact static geometry for the frontend. Sent once, not per tick.

        Racks are emitted as horizontal run-length spans so a 60x40 warehouse
        costs a few hundred bytes instead of 2400 cells.
        """
        spans = []
        for cy in range(self.height):
            cx = 0
            while cx < self.width:
                if self.grid[cy][cx] is Cell.RACK:
                    start = cx
                    while (cx < self.width
                           and self.grid[cy][cx] is Cell.RACK):
                        cx += 1
                    spans.append([start, cy, cx - start])
                else:
                    cx += 1
        return {
            "width": self.width,
            "height": self.height,
            "cell_m": CELL_M,
            "rack_spans": spans,
            # Blocked cells are forwarded so the map can draw the restricted
            # region. Sorted for a stable wire order, which keeps the payload
            # byte-identical across runs with the same blockage and therefore
            # keeps determinism receipts comparable.
            "blocked": sorted(self.blocked),
            "chargers": self.cells_of_type(Cell.CHARGER),
            "pick": self.cells_of_type(Cell.PICK),
            "drop": self.cells_of_type(Cell.DROP),
            "zones": [
                {"name": z.name, "x0": z.x0, "y0": z.y0,
                 "x1": z.x1, "y1": z.y1} for z in self.zones
            ],
        }

# File contains AI-generated response based on internal company sources
