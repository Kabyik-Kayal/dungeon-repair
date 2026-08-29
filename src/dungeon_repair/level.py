"""Level representation.

A dungeon is a directed graph. Rooms are nodes carrying contents (a key, the
boss key, the start, the goal); passages are edges carrying requirements (this
door is key-locked, that one needs the boss key). Passages are directed and
frequently asymmetric in the source data -- one direction of a door can be
free while the other is locked -- so they are stored as directed pairs rather
than collapsed into undirected doors.

Symbols follow the VGLC ``zelda.json`` legend. They are single characters, or
``S<n>`` for the n-th switch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator

# --- room contents (node labels) -------------------------------------------
START = "s"
GOAL = "t"  # "triforce" in the legend
SMALL_KEY = "k"
BOSS_KEY = "K"
KEY_ITEM = "I"
ENEMY = "e"
PUZZLE = "p"
BOSS = "b"

# --- passage requirements (edge labels) ------------------------------------
KEY_LOCKED = "k"
BOSS_KEY_LOCKED = "K"
KEY_ITEM_LOCKED = "I"
SOFT_LOCKED = "l"
BOMBABLE = "b"
IMPASSABLE = "s"  # legend: "visible, impassable"

#: Undocumented symbols that appear in the corpus. The legend does not define
#: them; they are carried through as opaque room contents and never gate a
#: passage. See docs/DATA_NOTES.md.
UNDOCUMENTED = frozenset({"i", "m", "O"})

SWITCH_PREFIX = "S"

ROOM_CONTENT_NAMES = {
    ENEMY: "enemy",
    BOSS: "boss",
    SMALL_KEY: "small key",
    BOSS_KEY: "boss key",
    KEY_ITEM: "key item",
    PUZZLE: "puzzle",
    START: "start",
    GOAL: "goal",
}

PASSAGE_REQ_NAMES = {
    KEY_LOCKED: "key-locked",
    BOSS_KEY_LOCKED: "boss-key-locked",
    KEY_ITEM_LOCKED: "key-item-locked",
    SOFT_LOCKED: "soft-locked",
    BOMBABLE: "bombable",
    IMPASSABLE: "impassable",
}


def is_switch(symbol: str) -> bool:
    """True for ``S``, ``S1``, ``S12`` -- a switch room or a switch-locked door."""
    return symbol.startswith(SWITCH_PREFIX) and (
        len(symbol) == 1 or symbol[1:].isdigit()
    )


def switch_id(symbol: str) -> str:
    """Normalise a switch symbol to its identifier. Bare ``S`` is switch ``0``."""
    return symbol[1:] or "0"


def describe_room(contents: Iterable[str]) -> str:
    named = [ROOM_CONTENT_NAMES.get(c) for c in sorted(contents)]
    named = [n for n in named if n]
    switches = [f"switch {switch_id(c)}" for c in sorted(contents) if is_switch(c)]
    parts = named + switches
    return ", ".join(parts) if parts else "empty"


def describe_passage(requires: Iterable[str]) -> str:
    named = [PASSAGE_REQ_NAMES.get(r) for r in sorted(requires)]
    named = [n for n in named if n]
    switches = [f"switch-{switch_id(r)}-locked" for r in sorted(requires) if is_switch(r)]
    parts = named + switches
    return ", ".join(parts) if parts else "open"


@dataclass(frozen=True, order=True)
class Passage:
    """One directed traversal from ``src`` to ``dst``."""

    src: str
    dst: str
    requires: frozenset[str] = frozenset()

    @property
    def door(self) -> tuple[str, str]:
        """The undirected door this passage belongs to (order-independent)."""
        return (self.src, self.dst) if self.src <= self.dst else (self.dst, self.src)

    def to_json(self) -> dict:
        return {"from": self.src, "to": self.dst, "requires": sorted(self.requires)}


@dataclass(frozen=True)
class Level:
    """A dungeon: typed rooms plus directed passages between them."""

    id: str
    game: str
    rooms: dict[str, frozenset[str]]
    passages: tuple[Passage, ...]

    # -- queries ------------------------------------------------------------
    def rooms_with(self, symbol: str) -> list[str]:
        return sorted(r for r, c in self.rooms.items() if symbol in c)

    @property
    def start(self) -> str | None:
        found = self.rooms_with(START)
        return found[0] if found else None

    @property
    def goals(self) -> frozenset[str]:
        return frozenset(self.rooms_with(GOAL))

    @property
    def key_rooms(self) -> list[str]:
        return self.rooms_with(SMALL_KEY)

    def doors(self) -> list[tuple[str, str]]:
        """Every undirected door, deduplicated, in stable order."""
        return sorted({p.door for p in self.passages})

    def passages_of(self, door: tuple[str, str]) -> list[Passage]:
        return [p for p in self.passages if p.door == door]

    def neighbours(self) -> dict[str, list[Passage]]:
        adj: dict[str, list[Passage]] = {r: [] for r in self.rooms}
        for p in self.passages:
            adj.setdefault(p.src, []).append(p)
        return adj

    def switch_ids(self) -> list[str]:
        """Every switch mentioned anywhere, as room content or door requirement."""
        found = {
            switch_id(sym)
            for group in list(self.rooms.values()) + [p.requires for p in self.passages]
            for sym in group
            if is_switch(sym)
        }
        return sorted(found)

    # -- edits (all return a new Level; Level is immutable) ------------------
    def with_room_contents(self, room: str, contents: frozenset[str]) -> "Level":
        rooms = dict(self.rooms)
        rooms[room] = contents
        return replace(self, rooms=rooms)

    def moved(self, symbol: str, src: str, dst: str) -> "Level":
        rooms = dict(self.rooms)
        rooms[src] = rooms[src] - {symbol}
        rooms[dst] = rooms[dst] | {symbol}
        return replace(self, rooms=rooms)

    def with_symbol_added(self, symbol: str, room: str) -> "Level":
        rooms = dict(self.rooms)
        rooms[room] = rooms[room] | {symbol}
        return replace(self, rooms=rooms)

    def with_door_requirements(
        self, door: tuple[str, str], requires: frozenset[str]
    ) -> "Level":
        """Replace the requirements on both directions of an existing door."""
        passages = tuple(
            replace(p, requires=requires) if p.door == door else p
            for p in self.passages
        )
        return replace(self, passages=passages)

    def with_door_added(
        self, a: str, b: str, requires: frozenset[str] = frozenset()
    ) -> "Level":
        """Add a two-way passage between two rooms."""
        added = (Passage(a, b, requires), Passage(b, a, requires))
        return replace(self, passages=self.passages + added)

    def without_door(self, door: tuple[str, str]) -> "Level":
        passages = tuple(p for p in self.passages if p.door != door)
        return replace(self, passages=passages)

    # -- serialisation ------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "id": self.id,
            "game": self.game,
            "rooms": {r: sorted(c) for r, c in sorted(self.rooms.items(), key=_room_key)},
            "passages": [p.to_json() for p in self.passages],
        }

    @classmethod
    def from_json(cls, data: dict) -> "Level":
        return cls(
            id=data["id"],
            game=data["game"],
            rooms={r: frozenset(c) for r, c in data["rooms"].items()},
            passages=tuple(
                Passage(p["from"], p["to"], frozenset(p["requires"]))
                for p in data["passages"]
            ),
        )

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=2) + "\n")

    @classmethod
    def read(cls, path: str | Path) -> "Level":
        return cls.from_json(json.loads(Path(path).read_text()))

    # -- human-readable -----------------------------------------------------
    def outline(self) -> str:
        """A compact text rendering, used in prompts and CLI output."""
        lines = [f"dungeon {self.id} ({self.game}): {len(self.rooms)} rooms, "
                 f"{len(self.doors())} doors"]
        lines.append("ROOMS")
        for room in sorted(self.rooms, key=lambda r: _room_key((r, None))):
            lines.append(f"  {room:>4}: {describe_room(self.rooms[room])}")
        lines.append("DOORS")
        for door in self.doors():
            reqs = {p.src: describe_passage(p.requires) for p in self.passages_of(door)}
            a, b = door
            fwd, bwd = reqs.get(a, "(no passage)"), reqs.get(b, "(no passage)")
            if fwd == bwd:
                lines.append(f"  {a} <-> {b}: {fwd}")
            else:
                lines.append(f"  {a}  -> {b}: {fwd}")
                lines.append(f"  {b}  -> {a}: {bwd}")
        return "\n".join(lines)


def _room_key(item: tuple[str, object]) -> tuple[int, object]:
    """Sort numeric room ids numerically, everything else lexically."""
    name = item[0]
    return (0, int(name)) if name.isdigit() else (1, name)


def iter_levels(paths: Iterable[str | Path]) -> Iterator[Level]:
    for path in paths:
        yield Level.read(path)
