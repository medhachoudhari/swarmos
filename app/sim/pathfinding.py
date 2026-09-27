"""SWARMOS M5 simulation - deterministic grid pathfinding.

A* over the 4-connected warehouse grid, with a strict total order on the open
set so that two runs with identical inputs always return the identical path.
Determinism is a published success criterion (X-22 trace hash), so ties are
never broken by dictionary or set iteration order.

Tie-break order, applied in sequence:
  1. lowest f = g + h
  2. lowest h (prefer the node closer to the goal, this expands fewer nodes)
  3. lowest insertion counter (first discovered wins, which is stable because
     Warehouse.neighbours returns a fixed N, S, W, E order)

The optional `cost_field` argument is the hook for the deferred congestion
aware planner (X-05) and for the M3 forecaster (X-20). When it is None the
search is a plain shortest path, which is what the default demo uses.
"""

from __future__ import annotations

import heapq
import math
from typing import Callable, Iterable, Optional

from app.sim.warehouse import Warehouse

Cellref = tuple[int, int]
CostField = Callable[[Cellref], float]

# Safety valve. A 60x40 warehouse has 2400 cells, so a well formed search can
# never expand more than that many nodes. The cap only fires on a bug.
MAX_EXPANSIONS = 200_000


def manhattan(a: Cellref, b: Cellref) -> int:
    """Admissible and consistent heuristic for a 4-connected unit-cost grid."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def find_path(
    warehouse: Warehouse,
    start: Cellref,
    goal: Cellref,
    *,
    cost_field: Optional[CostField] = None,
    avoid: Optional[Iterable[Cellref]] = None,
) -> Optional[list[Cellref]]:
    """Shortest 4-connected path from `start` to `goal`, inclusive of both.

    Returns None when no path exists, which is a legitimate outcome once the
    blocked_aisle scenario seals a corridor. Callers must handle None rather
    than assume a route is always available.

    `avoid` is a set of cells treated as temporarily impassable. The engine
    passes the last known coordinate of a failed robot here, which is how
    X-23 reroutes the fleet around a dead agent.
    """
    if not warehouse.is_navigable(*goal):
        return None
    if start == goal:
        return [start]
    if not warehouse.in_bounds(*start):
        return None

    blocked: set[Cellref] = set(avoid) if avoid else set()
    if goal in blocked:
        # The goal itself is the thing we were told to avoid. Refuse rather
        # than silently route into it.
        return None

    counter = 0
    # heap entries are (f, h, counter, cell)
    open_heap: list[tuple[float, int, int, Cellref]] = []
    h0 = manhattan(start, goal)
    heapq.heappush(open_heap, (float(h0), h0, counter, start))

    came_from: dict[Cellref, Cellref] = {}
    g_score: dict[Cellref, float] = {start: 0.0}
    closed: set[Cellref] = set()

    expansions = 0

    while open_heap:
        _f, _h, _c, current = heapq.heappop(open_heap)

        if current in closed:
            # Stale heap entry left over from an improved g value.
            continue
        closed.add(current)

        if current == goal:
            return _reconstruct(came_from, current)

        expansions += 1
        if expansions > MAX_EXPANSIONS:
            raise RuntimeError(
                "A* expansion cap exceeded, warehouse graph is likely malformed"
            )

        for neighbour in warehouse.neighbours(*current):
            if neighbour in closed or neighbour in blocked:
                continue

            step_cost = 1.0
            if cost_field is not None:
                # Extra cost is additive and must be non-negative, otherwise
                # the heuristic stops being admissible.
                extra = cost_field(neighbour)
                if extra < 0.0:
                    extra = 0.0
                step_cost += extra

            tentative = g_score[current] + step_cost
            if tentative < g_score.get(neighbour, float("inf")):
                came_from[neighbour] = current
                g_score[neighbour] = tentative
                h = manhattan(neighbour, goal)
                counter += 1
                heapq.heappush(
                    open_heap, (tentative + h, h, counter, neighbour)
                )

    return None


def _reconstruct(came_from: dict[Cellref, Cellref], node: Cellref) -> list[Cellref]:
    path = [node]
    while node in came_from:
        node = came_from[node]
        path.append(node)
    path.reverse()
    return path


def nearest_navigable(
    warehouse: Warehouse, cell: Cellref, *, max_radius: int = 6
) -> Optional[Cellref]:
    """Find the closest navigable cell to `cell` by expanding ring radius.

    PICK and DROP cells sit against racks, and a blockage can land directly on
    a robot. This gives the engine a deterministic way to recover: rings are
    scanned in increasing radius, and within a radius in sorted cell order.
    """
    if warehouse.is_navigable(*cell):
        return cell

    cx, cy = cell
    for radius in range(1, max_radius + 1):
        ring: list[Cellref] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                candidate = (cx + dx, cy + dy)
                if warehouse.is_navigable(*candidate):
                    ring.append(candidate)
        if ring:
            # Sorted so the choice never depends on iteration order.
            return sorted(ring)[0]
    return None


def path_to_metres(
    warehouse: Warehouse, cells: list[Cellref]
) -> list[tuple[float, float]]:
    """Convert a cell path into metre-space waypoints at cell centres.

    The conversion itself lives in Warehouse (the single owner of grid<->metre
    per the frozen conventions); this is only a mapping helper.
    """
    return [warehouse.cell_to_m(cx, cy) for cx, cy in cells]


def simplify_collinear(
    waypoints: list[tuple[float, float]], *, eps: float = 1e-9
) -> list[tuple[float, float]]:
    """Drop interior waypoints that lie on a straight run.

    A 40 cell straight aisle traversal becomes 2 waypoints instead of 40. This
    matters because the full path is published inside MovementIntent and
    crosses the websocket, and because it reduces per-tick waypoint popping.
    Geometry is unchanged, so reservations computed from the cell path stay
    valid.
    """
    if len(waypoints) <= 2:
        return list(waypoints)

    out = [waypoints[0]]
    for prev, cur, nxt in zip(waypoints, waypoints[1:], waypoints[2:]):
        cross = (cur[0] - prev[0]) * (nxt[1] - prev[1]) - (
            cur[1] - prev[1]
        ) * (nxt[0] - prev[0])
        if abs(cross) > eps:
            out.append(cur)
    out.append(waypoints[-1])
    return out


def trim_passed_start(
    waypoints: list[tuple[float, float]],
    position: tuple[float, float],
    *,
    tol_m: float = 1e-6,
) -> list[tuple[float, float]]:
    """Drop waypoint 0 when the robot already stands on the first leg past it.

    find_path starts at the cell the robot is IN, and path_to_metres turns that
    cell into its centre. A robot halted part-way between two cell centres is
    therefore handed a path whose first waypoint lies behind it on the very
    line it is about to drive forward along. Following it literally makes the
    robot reverse to the cell centre and then drive forward over the same
    ground again - motion no real planner would command, and motion the safety
    monitor's forward-looking step geometry did not anticipate. See
    docs/COORDINATION_FIXES_BATCH1.md.

    The first waypoint is dropped only when the robot lies ON the segment from
    waypoint 0 to waypoint 1, strictly past waypoint 0 and short of waypoint 1.
    Then heading straight for waypoint 1 retraces nothing and stays on the same
    grid line, so no new ground is entered. In every other case - including a
    robot that must go back to the cell centre to make a turn - the path is
    returned unchanged.

    Pure and deterministic; shared by every policy because it lives in the
    simulator, not in any arbiter.
    """
    if len(waypoints) < 2:
        return list(waypoints)
    (ax, ay), (bx, by) = waypoints[0], waypoints[1]
    ux, uy = bx - ax, by - ay
    leg = math.hypot(ux, uy)
    if leg <= tol_m:
        return list(waypoints)
    px, py = position
    along = ((px - ax) * ux + (py - ay) * uy) / leg
    across = abs((px - ax) * uy - (py - ay) * ux) / leg
    if across <= tol_m and tol_m < along < leg - tol_m:
        return list(waypoints[1:])
    return list(waypoints)


def path_length_cells(cells: list[Cellref]) -> int:
    """Number of moves in a cell path. Used as the auction distance term."""
    return max(0, len(cells) - 1)

# File contains AI-generated response based on internal company sources
