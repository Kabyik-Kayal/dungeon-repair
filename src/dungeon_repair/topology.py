"""Structural helpers: distances between rooms, and how much of a layout survives an edit."""

from __future__ import annotations

from collections import deque

from .level import Level


def undirected_adjacency(level: Level) -> dict[str, set[str]]:
    """Room adjacency ignoring every lock -- pure topology, not reachability."""
    adj: dict[str, set[str]] = {r: set() for r in level.rooms}
    for p in level.passages:
        adj.setdefault(p.src, set()).add(p.dst)
        adj.setdefault(p.dst, set()).add(p.src)
    return adj


def distances_from(level: Level, origin: str) -> dict[str, int]:
    """Hop counts from ``origin``, ignoring locks. Unreachable rooms are omitted."""
    adj = undirected_adjacency(level)
    seen = {origin: 0}
    queue = deque([origin])
    while queue:
        room = queue.popleft()
        for nb in adj.get(room, ()):
            if nb not in seen:
                seen[nb] = seen[room] + 1
                queue.append(nb)
    return seen


def hop_distance(level: Level, a: str, b: str) -> int | None:
    return distances_from(level, a).get(b)


def layout_signature(level: Level) -> tuple[frozenset, frozenset]:
    """What "the layout" means for preservation scoring: doors and room contents."""
    doors = frozenset(
        (p.door, frozenset(p.requires)) for p in level.passages
    )
    contents = frozenset(level.rooms.items())
    return doors, contents


def layout_preservation(original: Level, candidate: Level) -> float:
    """Fraction of the original layout still present, in [0, 1].

    Jaccard similarity over the union of doors-with-their-locks and
    room-contents assignments. A single-edit repair scores near 1; a level
    regenerated from scratch scores near 0.
    """
    o_doors, o_rooms = layout_signature(original)
    c_doors, c_rooms = layout_signature(candidate)
    o_all, c_all = o_doors | o_rooms, c_doors | c_rooms
    if not o_all and not c_all:
        return 1.0
    return len(o_all & c_all) / len(o_all | c_all)
