"""What the designer's other dungeons look like.

The failure this project could not shift is that the agent names the right bug
roughly twice as often as it produces the right repair. The changelog's
explanation was that choosing where a key belongs needs the dungeon's design
rhythm -- an alcove before every gate -- and that nothing in the tools exposes
rhythm, only distance, topology and key counts.

This module measures the rhythm instead of assuming it, and the measurement is
worth stating plainly because it is not what was assumed:

* Keys are **not** reliably placed before the gate they open. In the shipped
  corpus 102 of 127 keys sit beyond their nearest locked door, not in front of
  it. The alcove story is wrong for this corpus.
* What is true is much duller. **76% of key rooms contain an enemy against a
  52% base rate** (lift 1.45) -- you fight for the key. Keys cluster: half sit
  within two rooms of another key. Key items and small keys almost never share
  a room (lift 0.23).
* Those motifs **narrow, they do not rank.** Scoring rooms by a log-prior over
  them recovers 2 of 15 displaced keys, no better than plain topology. Used as
  a filter, "the home room contains an enemy" keeps 13 of 24 candidates and
  retains the true one in 13 of 15 cases.

So this is deliberately not a ranker. It is evidence handed to the agent, with
its own lift printed next to it, because the one thing measurement has shown
repeatedly here is that the agent combines weak signals better than any fixed
ordering built on top of them.

Every statistic is mined **excluding the dungeon under repair**, so nothing the
agent reads is derived from the level it is being scored on.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable

from .level import (
    ENEMY,
    KEY_ITEM,
    KEY_LOCKED,
    Level,
    PUZZLE,
    SMALL_KEY,
    describe_room,
)

#: Room contents worth reporting a lift for. Anything rarer is noise at this
#: corpus size.
TRACKED = (ENEMY, PUZZLE, KEY_ITEM)

NEAR = 2  # "within a couple of rooms", in hops


def _adjacency(level: Level) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = defaultdict(set)
    for passage in level.passages:
        adj[passage.src].add(passage.dst)
        adj[passage.dst].add(passage.src)
    for room in level.rooms:
        adj.setdefault(room, set())
    return adj


def _hops(adj: dict[str, set[str]], source: str) -> dict[str, int]:
    seen = {source: 0}
    queue = deque([source])
    while queue:
        room = queue.popleft()
        for nxt in adj[room]:
            if nxt not in seen:
                seen[nxt] = seen[room] + 1
                queue.append(nxt)
    return seen


def key_locked_doors(level: Level) -> list[tuple[str, str]]:
    return [
        door for door in level.doors()
        if any(KEY_LOCKED in p.requires for p in level.passages_of(door))
    ]


@dataclass
class Motif:
    """One measured regularity, carrying the numbers that justify it."""

    name: str
    among_key_rooms: int
    key_rooms: int
    among_all_rooms: int
    all_rooms: int

    @property
    def rate(self) -> float:
        return self.among_key_rooms / self.key_rooms if self.key_rooms else 0.0

    @property
    def base(self) -> float:
        return self.among_all_rooms / self.all_rooms if self.all_rooms else 0.0

    @property
    def lift(self) -> float:
        return self.rate / self.base if self.base else 0.0

    #: A motif that fires on most rooms separates nothing, however real it is.
    #: The band is deliberately wide: everything inside it is reported by
    #: `summary()` and withheld from per-option annotation.
    @property
    def discriminating(self) -> bool:
        return self.lift >= 1.35 or self.lift <= 0.75

    def line(self) -> str:
        return (
            f"  {self.name:<34} {self.rate:5.0%} of key rooms vs {self.base:5.0%} "
            f"of all rooms  (lift {self.lift:.2f})"
            + ("" if self.discriminating else "   [too weak to separate options]")
        )


@dataclass
class DesignMemory:
    """Motifs mined from every dungeon except the one being repaired."""

    source: str = ""
    dungeons: int = 0
    motifs: list[Motif] = field(default_factory=list)
    keys_per_dungeon: float = 0.0
    locks_per_dungeon: float = 0.0

    def by_name(self, name: str) -> Motif | None:
        for motif in self.motifs:
            if motif.name == name:
                return motif
        return None

    def summary(self) -> str:
        if not self.dungeons:
            return "No other dungeons to compare against."
        lines = [
            f"Measured across {self.dungeons} other dungeons by the same designers "
            f"(this one excluded), {self.keys_per_dungeon:.1f} small keys and "
            f"{self.locks_per_dungeon:.1f} key-locked doors each.",
            "Where a small key tends to sit:",
        ]
        lines += [m.line() for m in self.motifs]
        lines.append(
            "Read these as filters, not as a ranking: on this corpus they cut the "
            "plausible home rooms roughly in half while keeping the right one, and "
            "they are far too weak to pick between what survives. The judgement is "
            "still yours."
        )
        return "\n".join(lines)

    def matches(self, level: Level, room: str) -> list[str]:
        """Which *discriminating* motifs this room satisfies.

        A motif that fires on four rooms in five separates nothing, and
        printing it against every option is clutter dressed as evidence. Only
        motifs that actually move the odds are annotated; `summary()` still
        reports all of them, weak ones included, so the agent can see what was
        measured and what was withheld.
        """
        if room not in level.rooms:
            return []
        adj = _adjacency(level)
        contents = level.rooms[room]
        hops = _hops(adj, room)
        keys = [r for r in level.key_rooms if r != room]
        ends = {r for door in key_locked_doors(level) for r in door}
        held = {
            "holds an enemy": ENEMY in contents,
            "holds a puzzle": PUZZLE in contents,
            "holds the key item": KEY_ITEM in contents,
            "is a dead end": len(adj[room]) == 1,
            f"within {NEAR} rooms of another key": bool(keys) and min(
                (hops.get(k, 99) for k in keys), default=99
            ) <= NEAR,
            f"within {NEAR} rooms of a key-locked door": bool(ends) and min(
                (hops.get(e, 99) for e in ends), default=99
            ) <= NEAR,
        }
        out = []
        for motif in self.motifs:
            if not held.get(motif.name):
                continue
            if not motif.discriminating:
                continue
            direction = "" if motif.lift >= 1 else " -- keys avoid this"
            out.append(f"{motif.name} (lift {motif.lift:.2f}{direction})")
        return out

    def annotate(self, level: Level, room: str) -> str:
        found = self.matches(level, room)
        return f"  [{'; '.join(found)}]" if found else ""


def mine(levels: Iterable[Level], exclude: str = "") -> DesignMemory:
    """Measure the motifs, holding out the dungeon under repair.

    ``exclude`` is matched against ``Level.id``. Holding it out is what makes
    the memory evidence rather than leakage: nothing the agent reads about the
    level it is repairing came from that level.
    """
    counters = {
        "holds an enemy": (ENEMY, "content"),
        "holds a puzzle": (PUZZLE, "content"),
        "holds the key item": (KEY_ITEM, "content"),
        f"within {NEAR} rooms of another key": (None, "near_key"),
        f"within {NEAR} rooms of a key-locked door": (None, "near_lock"),
        "is a dead end": (None, "dead_end"),
    }
    among_key: Counter = Counter()
    among_all: Counter = Counter()
    key_rooms = all_rooms = dungeons = 0
    total_keys = total_locks = 0

    for level in levels:
        if level.id == exclude:
            continue
        dungeons += 1
        adj = _adjacency(level)
        keys = set(level.key_rooms)
        doors = key_locked_doors(level)
        ends = {r for door in doors for r in door}
        total_keys += len(keys)
        total_locks += len(doors)
        for room, contents in level.rooms.items():
            hops = _hops(adj, room)
            is_key = room in keys
            all_rooms += 1
            key_rooms += 1 if is_key else 0
            for name, (symbol, mode) in counters.items():
                if mode == "content":
                    holds = symbol in contents
                elif mode == "near_key":
                    holds = min(
                        (hops.get(k, 99) for k in keys if k != room), default=99
                    ) <= NEAR
                elif mode == "near_lock":
                    holds = min((hops.get(e, 99) for e in ends), default=99) <= NEAR
                else:
                    holds = len(adj[room]) == 1
                if holds:
                    among_all[name] += 1
                    if is_key:
                        among_key[name] += 1

    motifs = [
        Motif(name, among_key[name], key_rooms, among_all[name], all_rooms)
        for name in counters
    ]
    motifs.sort(key=lambda m: -abs(m.lift - 1.0))
    return DesignMemory(
        source="corpus",
        dungeons=dungeons,
        motifs=motifs,
        keys_per_dungeon=total_keys / dungeons if dungeons else 0.0,
        locks_per_dungeon=total_locks / dungeons if dungeons else 0.0,
    )
