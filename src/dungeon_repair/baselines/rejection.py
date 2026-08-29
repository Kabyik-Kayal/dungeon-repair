"""Baseline 1: rejection sampling -- what teams actually do today.

Throw the level away, generate a fresh one to the same spec (room count, door
count, key count, lock count), and keep rerolling until the solver passes. It
always produces a winnable dungeon and it never produces *this* dungeon: every
hand-placed corridor and every deliberate key position is gone. It is in the
comparison to put a number on that cost, not because it is a serious rival.
"""

from __future__ import annotations

import random
import time

from ..corrupt import Case
from ..level import (
    BOSS_KEY,
    BOSS_KEY_LOCKED,
    GOAL,
    KEY_ITEM,
    KEY_ITEM_LOCKED,
    KEY_LOCKED,
    Level,
    Passage,
    START,
    SMALL_KEY,
)
from ..metrics import Attempt, score
from ..solver import solve

METHOD = "rejection"
MAX_ROLLS = 200


def _spec(level: Level) -> dict:
    locked = {
        req
        for p in level.passages
        for req in p.requires
        if req in (KEY_LOCKED, BOSS_KEY_LOCKED, KEY_ITEM_LOCKED)
    }
    return {
        "rooms": sorted(level.rooms),
        "doors": len(level.doors()),
        "keys": len(level.key_rooms),
        "key_doors": sum(
            1 for d in level.doors()
            if any(KEY_LOCKED in p.requires for p in level.passages_of(d))
        ),
        "has_boss_key": bool(level.rooms_with(BOSS_KEY)),
        "has_key_item": bool(level.rooms_with(KEY_ITEM)),
        "lock_types": sorted(locked),
    }


def generate(spec: dict, rng: random.Random, level_id: str, game: str) -> Level:
    """A fresh dungeon to the same spec: random spanning tree plus extra doors."""
    rooms = list(spec["rooms"])
    rng.shuffle(rooms)

    doors: list[tuple[str, str]] = []
    connected = [rooms[0]]
    for room in rooms[1:]:
        doors.append((rng.choice(connected), room))
        connected.append(room)
    possible = [
        (a, b)
        for i, a in enumerate(rooms)
        for b in rooms[i + 1:]
        if (a, b) not in doors and (b, a) not in doors
    ]
    rng.shuffle(possible)
    doors += possible[: max(0, spec["doors"] - len(doors))]

    key_doors = set(rng.sample(range(len(doors)), min(spec["key_doors"], len(doors))))
    passages: list[Passage] = []
    for i, (a, b) in enumerate(doors):
        requires = frozenset({KEY_LOCKED}) if i in key_doors else frozenset()
        passages += [Passage(a, b, requires), Passage(b, a, requires)]

    contents: dict[str, set[str]] = {r: set() for r in rooms}
    pool = list(rooms)
    rng.shuffle(pool)
    contents[pool[0]].add(START)
    contents[pool[-1]].add(GOAL)
    middle = pool[1:-1] or pool
    for room in rng.sample(middle, min(spec["keys"], len(middle))):
        contents[room].add(SMALL_KEY)
    if spec["has_boss_key"]:
        contents[rng.choice(middle)].add(BOSS_KEY)
    if spec["has_key_item"]:
        contents[rng.choice(middle)].add(KEY_ITEM)

    return Level(
        id=level_id,
        game=game,
        rooms={r: frozenset(c) for r, c in contents.items()},
        passages=tuple(passages),
    )


def run(case: Case, seed: int = 0, **_: object) -> Attempt:
    started = time.perf_counter()
    rng = random.Random(f"{case.id}:{seed}")
    spec = _spec(case.original)
    rolls = 0
    level = case.broken
    for rolls in range(1, MAX_ROLLS + 1):
        level = generate(spec, rng, case.broken.id, case.broken.game)
        if solve(level).solvable:
            break
    return score(
        case,
        METHOD,
        None,
        time.perf_counter() - started,
        repaired=level,
        usage={"cost_usd": 0.0, "calls": 0},
        rationale=f"regenerated the dungeon from scratch; {rolls} roll(s) to pass",
        extra={"rolls": rolls},
    )
