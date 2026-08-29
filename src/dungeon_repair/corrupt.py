"""Seeded corruption: break a shipped dungeon in a way a generator plausibly would.

Each corruption is a single mutation whose inverse is expressible in the same
edit vocabulary the repairer uses. Because the mutation is known, the
designer's intended repair is known, so "did the repair recover the intent"
is an objective question rather than a taste test.

Corruptions are sampled and then kept only if the solver confirms the level is
genuinely unwinnable afterwards. That filter is what makes the cases hard:
mutations that touch a redundant corridor or a spare key are discarded, so
every surviving case sits on the critical path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .edits import ADD_DOOR, Edit, MOVE_KEY, UNLOCK
from .level import KEY_LOCKED, Level, SMALL_KEY
from .solver import solve

#: How a generator breaks a level, and what it looks like to a designer.
DISPLACED_KEY = "displaced_key"
SEVERED_CORRIDOR = "severed_corridor"
SPURIOUS_LOCK = "spurious_lock"

KIND_STORY = {
    DISPLACED_KEY: "a small key was placed in the wrong room",
    SEVERED_CORRIDOR: "a corridor between two rooms was dropped",
    SPURIOUS_LOCK: "a lock was added to a door that should be open",
}


@dataclass
class Case:
    """One evaluation case: a broken level plus the repair that undoes the break."""

    id: str
    game: str
    source_level: str
    kind: str
    broken: Level
    original: Level
    truth: Edit
    #: Free-text note for hand-authored cases.
    note: str = ""

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "game": self.game,
            "source_level": self.source_level,
            "kind": self.kind,
            "story": KIND_STORY.get(self.kind, self.note),
            "note": self.note,
            "truth": self.truth.to_json(),
            "broken": self.broken.to_json(),
            "original": self.original.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict) -> "Case":
        return cls(
            id=data["id"],
            game=data["game"],
            source_level=data["source_level"],
            kind=data["kind"],
            broken=Level.from_json(data["broken"]),
            original=Level.from_json(data["original"]),
            truth=Edit.from_json(data["truth"]),
            note=data.get("note", ""),
        )


def _free_doors(level: Level) -> list[tuple[str, str]]:
    """Doors that are open in both directions -- the ones a generator can lose."""
    out = []
    for door in level.doors():
        passages = level.passages_of(door)
        if len(passages) == 2 and all(not p.requires for p in passages):
            out.append(door)
    return out


def corrupt_once(level: Level, rng: random.Random, kind: str | None = None) -> tuple[Level, str, Edit] | None:
    """Apply one mutation. Returns ``(broken level, kind, inverse edit)``."""
    key_rooms = level.key_rooms
    free = _free_doors(level)

    options = []
    if key_rooms and len(level.rooms) > 1:
        options.append(DISPLACED_KEY)
    if free:
        options += [SEVERED_CORRIDOR, SPURIOUS_LOCK]
    if kind is not None:
        options = [kind] if kind in options else []
    if not options:
        return None
    chosen = rng.choice(options)

    if chosen == DISPLACED_KEY:
        src = rng.choice(key_rooms)
        # The destination must not already hold a key: moving a key onto an
        # existing one is not undoable by a single move, so the case would have
        # no ground truth in the edit vocabulary.
        elsewhere = [
            r for r in sorted(level.rooms)
            if r != src and SMALL_KEY not in level.rooms[r]
        ]
        if not elsewhere:
            return None
        dst = rng.choice(elsewhere)
        return level.moved(SMALL_KEY, src, dst), chosen, Edit(MOVE_KEY, dst, src)

    door = rng.choice(free)
    if chosen == SEVERED_CORRIDOR:
        return level.without_door(door), chosen, Edit(ADD_DOOR, *door)

    broken = level.with_door_requirements(door, frozenset({KEY_LOCKED}))
    return broken, chosen, Edit(UNLOCK, *door)


def build_cases(
    levels: Iterable[Level],
    per_kind: int = 1,
    seed: int = 1234,
    attempts: int = 40,
    kinds: tuple[str, ...] = (DISPLACED_KEY, SEVERED_CORRIDOR, SPURIOUS_LOCK),
) -> list[Case]:
    """Generate an evaluation set of genuinely-broken levels.

    Only levels the solver certifies as winnable are corrupted, and only
    mutations that actually break winnability are kept. Sampling is balanced
    across corruption kinds: an unbalanced sampler buries displaced keys under
    severed corridors, because cutting a corridor breaks a dungeon far more
    often than moving a key does, and the displaced key is the failure the
    problem statement is actually about.
    """
    rng = random.Random(seed)
    cases: list[Case] = []
    for level in levels:
        if not solve(level).solvable:
            continue
        made = 0
        for kind in kinds:
            found = 0
            seen: set[tuple[str, str, str]] = set()
            for _ in range(attempts):
                if found == per_kind:
                    break
                attempt = corrupt_once(level, rng, kind=kind)
                if attempt is None:
                    break
                broken, actual_kind, truth = attempt
                fingerprint = (actual_kind, truth.a, truth.b)
                if fingerprint in seen or solve(broken).solvable:
                    continue
                seen.add(fingerprint)
                found += 1
                made += 1
                cases.append(
                    Case(
                        id=f"{level.id}#{made}",
                        game=level.game,
                        source_level=level.id,
                        kind=actual_kind,
                        broken=broken,
                        original=level,
                        truth=truth,
                    )
                )
    return cases


def write_cases(cases: list[Case], directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    import json

    for case in cases:
        name = case.id.replace("#", "_") + ".json"
        (directory / name).write_text(json.dumps(case.to_json(), indent=2) + "\n")
    return directory


def read_cases(directory: str | Path) -> list[Case]:
    import json

    directory = Path(directory)
    cases = [
        Case.from_json(json.loads(p.read_text()))
        for p in sorted(directory.glob("*.json"))
    ]
    cases.sort(key=lambda c: (c.game, c.source_level, c.id))
    return cases
