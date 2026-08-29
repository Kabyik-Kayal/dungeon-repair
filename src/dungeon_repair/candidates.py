"""Enumerate every single edit that provably repairs a broken level.

This is the measurement that reshaped the project. Enumerating the edit
vocabulary and asking the solver about each one repairs essentially every
broken level, deterministically, in about a second, for no API spend. What it
cannot do is pick well: there is a median of ~100 provably-correct repairs per
broken level, and the first one in any fixed order is almost never the repair
the designer meant.

So this module is not the product. It is the oracle the agent chooses from --
correctness is settled here, and judgment is the only thing left.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterator

from .edits import ADD_DOOR, ADD_KEY, Edit, MOVE_KEY, UNLOCK
from .level import Level, SMALL_KEY
from .solver import solve

#: Least invasive first. An unlock or a key move leaves the floor plan intact;
#: adding a key inflates the key economy; a new corridor rewrites topology.
#: The deterministic baseline takes the first valid edit in exactly this order,
#: so the order is chosen to make that baseline as strong as it reasonably can be.
KIND_ORDER = (UNLOCK, MOVE_KEY, ADD_KEY, ADD_DOOR)


def _room_sort_key(room: str) -> tuple[int, object]:
    return (0, int(room)) if room.isdigit() else (1, room)


def enumerate_edits(level: Level) -> Iterator[Edit]:
    """Every single edit in the vocabulary, in a stable least-invasive-first order."""
    rooms = sorted(level.rooms, key=_room_sort_key)

    locked = [
        door for door in level.doors()
        if any(p.requires for p in level.passages_of(door))
    ]
    for door in locked:
        yield Edit(UNLOCK, *door)

    for src in sorted(level.key_rooms, key=_room_sort_key):
        for dst in rooms:
            if dst != src:
                yield Edit(MOVE_KEY, src, dst)

    for room in rooms:
        if SMALL_KEY not in level.rooms[room]:
            yield Edit(ADD_KEY, room)

    present = {p.door for p in level.passages}
    for a, b in combinations(rooms, 2):
        if (a, b) not in present and (b, a) not in present:
            yield Edit(ADD_DOOR, a, b)


@dataclass
class CandidateSet:
    """Every verified repair for one broken level, plus what it cost to find them."""

    level: Level
    verified: list[Edit] = field(default_factory=list)
    considered: int = 0
    seconds: float = 0.0

    def by_kind(self) -> dict[str, list[Edit]]:
        out: dict[str, list[Edit]] = {kind: [] for kind in KIND_ORDER}
        for edit in self.verified:
            out[edit.kind].append(edit)
        return out

    def counts(self) -> dict[str, int]:
        return {kind: len(edits) for kind, edits in self.by_kind().items()}

    def __len__(self) -> int:
        return len(self.verified)

    def __contains__(self, edit: object) -> bool:
        return edit in set(self.verified)


def verified_candidates(level: Level) -> CandidateSet:
    """Apply every edit in the vocabulary and keep the ones the solver certifies."""
    started = time.perf_counter()
    found: list[Edit] = []
    considered = 0
    for edit in enumerate_edits(level):
        considered += 1
        if solve(edit.apply(level)).solvable:
            found.append(edit)
    return CandidateSet(
        level=level,
        verified=found,
        considered=considered,
        seconds=time.perf_counter() - started,
    )


def first_valid(level: Level) -> tuple[Edit | None, int, float]:
    """The deterministic repairer: stop at the first edit that verifies.

    Returns ``(edit, edits considered, seconds)``.
    """
    started = time.perf_counter()
    considered = 0
    for edit in enumerate_edits(level):
        considered += 1
        if solve(edit.apply(level)).solvable:
            return edit, considered, time.perf_counter() - started
    return None, considered, time.perf_counter() - started


def verify(level: Level, edit: Edit) -> bool:
    """Does this single edit make the level winnable?"""
    return solve(edit.apply(level)).solvable
