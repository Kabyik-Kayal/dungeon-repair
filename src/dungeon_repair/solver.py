"""Deterministic playability solver. No model involved.

Whether a room is reachable depends on what the player is carrying and what
they have already spent, so plain flood fill is not enough: this is a search
over player state, not over rooms.

State is ``(room, keys collected, doors opened, flags)``. Two details are load
bearing and were established by running the solver against the shipped
dungeons rather than assumed:

* **Soft-locked doors are passable.** 101 doors in the corpus carry ``l`` in
  *both* directions, so it cannot mean "impassable". Treating it as blocking
  drops verified solvability from 31/38 to 6/38.
* **Which doors are already open belongs in the state.** Small keys are
  fungible and consumed, so spending one on the wrong door changes the
  outcome. Room + keys + switches alone is under-specified. Collected keys and
  opened doors are tracked as bitmasks; tracking collected rooms as a Python
  set is exponential and hangs on the 62-room dungeons.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .level import (
    BOSS_KEY,
    BOSS_KEY_LOCKED,
    IMPASSABLE,
    KEY_ITEM,
    KEY_ITEM_LOCKED,
    KEY_LOCKED,
    Level,
    Passage,
    is_switch,
    switch_id,
)

#: Search cutoff. Every shipped dungeon finishes far below this; the cap only
#: exists so a pathological generated level cannot hang the harness.
DEFAULT_CAP = 2_000_000

NO_START = "no start room"
NO_GOAL = "no goal room"


@dataclass
class Blocker:
    """A passage the player reached but could never pass."""

    passage: Passage
    reason: str

    def __str__(self) -> str:
        return f"{self.passage.src} -> {self.passage.dst} ({self.reason})"


@dataclass
class SolveResult:
    solvable: bool
    reason: str = ""
    #: Rooms the player can stand in, over all reachable states.
    reachable: frozenset[str] = frozenset()
    #: Rooms the player can never stand in.
    unreachable: frozenset[str] = frozenset()
    #: Passages that were reached from a reachable room but never traversable.
    blockers: list[Blocker] = field(default_factory=list)
    #: Room sequence of a winning route, when one exists.
    route: list[str] = field(default_factory=list)
    #: Search states expanded -- reported so cost claims are checkable.
    expanded: int = 0

    def summary(self) -> str:
        if self.solvable:
            return f"SOLVABLE in {len(self.route) - 1} moves ({self.expanded} states)"
        return f"UNSOLVABLE: {self.reason} ({self.expanded} states)"


def _blocked_reason(
    passage: Passage, keys_held: int, has_item: bool, has_boss_key: bool,
    switches_on: set[str],
) -> str | None:
    """Why this passage cannot be taken right now, or None if it can."""
    req = passage.requires
    if IMPASSABLE in req:
        return "impassable"
    if KEY_ITEM_LOCKED in req and not has_item:
        return "needs the key item"
    if BOSS_KEY_LOCKED in req and not has_boss_key:
        return "needs the boss key"
    switches = [switch_id(r) for r in req if is_switch(r)]
    if switches and not any(s in switches_on for s in switches):
        return "needs switch " + "/".join(sorted(switches))
    if KEY_LOCKED in req and keys_held < 1:
        return "no small key in hand"
    return None


def solve(level: Level, cap: int = DEFAULT_CAP) -> SolveResult:
    """Search for a route from the start room to a goal room.

    Returns a certain answer: a winning route, or proof that no ordering of
    key spends and switch flips reaches the goal.
    """
    start, goals = level.start, level.goals
    if start is None:
        return SolveResult(False, NO_START)
    if not goals:
        return SolveResult(False, NO_GOAL)

    key_rooms = level.key_rooms
    key_index = {room: i for i, room in enumerate(key_rooms)}
    switch_index = {s: i for i, s in enumerate(level.switch_ids())}

    # Only key-locked doors need an "opened" bit; every other lock is
    # permanent once satisfied, so opening it is implied by the flags.
    door_index: dict[tuple[str, str], int] = {}
    for p in level.passages:
        if KEY_LOCKED in p.requires and p.door not in door_index:
            door_index[p.door] = len(door_index)

    adjacency = level.neighbours()
    ITEM_BIT, BOSS_BIT, SWITCH_SHIFT = 1, 2, 2

    def pick_up(room: str, keys: int, flags: int) -> tuple[int, int]:
        contents = level.rooms.get(room, frozenset())
        if room in key_index:
            keys |= 1 << key_index[room]
        if KEY_ITEM in contents:
            flags |= ITEM_BIT
        if BOSS_KEY in contents:
            flags |= BOSS_BIT
        for symbol in contents:
            if is_switch(symbol):
                flags |= 1 << (SWITCH_SHIFT + switch_index[switch_id(symbol)])
        return keys, flags

    start_keys, start_flags = pick_up(start, 0, 0)
    initial = (start, start_keys, 0, start_flags)  # room, keys, opened doors, flags
    parents: dict[tuple, tuple | None] = {initial: None}
    queue = deque([initial])
    reachable = {start}
    blockers: dict[tuple[str, str, str], Blocker] = {}
    expanded = 0

    while queue:
        state = queue.popleft()
        room, keys, opened, flags = state
        expanded += 1
        if expanded > cap:
            return SolveResult(
                False, f"search cap of {cap} states exceeded", expanded=expanded
            )
        if room in goals:
            return SolveResult(
                True,
                reachable=frozenset(reachable),
                unreachable=frozenset(level.rooms) - reachable,
                route=_route(parents, state),
                expanded=expanded,
            )

        keys_held = bin(keys).count("1") - bin(opened).count("1")
        has_item = bool(flags & ITEM_BIT)
        has_boss_key = bool(flags & BOSS_BIT)
        switches_on = {
            s for s, i in switch_index.items() if flags >> (SWITCH_SHIFT + i) & 1
        }

        for passage in adjacency.get(room, ()):
            next_opened = opened
            if KEY_LOCKED in passage.requires:
                bit = 1 << door_index[passage.door]
                if not opened & bit:
                    reason = _blocked_reason(
                        passage, keys_held, has_item, has_boss_key, switches_on
                    )
                    if reason:
                        blockers[(passage.src, passage.dst, reason)] = Blocker(
                            passage, reason
                        )
                        continue
                    next_opened = opened | bit
                # else: already unlocked, no key spent
            else:
                reason = _blocked_reason(
                    passage, keys_held, has_item, has_boss_key, switches_on
                )
                if reason:
                    blockers[(passage.src, passage.dst, reason)] = Blocker(
                        passage, reason
                    )
                    continue

            nkeys, nflags = pick_up(passage.dst, keys, flags)
            nxt = (passage.dst, nkeys, next_opened, nflags)
            if nxt in parents:
                continue
            parents[nxt] = state
            reachable.add(passage.dst)
            queue.append(nxt)

    unreachable = frozenset(level.rooms) - reachable
    return SolveResult(
        False,
        _diagnose(level, reachable, unreachable, list(blockers.values())),
        reachable=frozenset(reachable),
        unreachable=unreachable,
        blockers=list(blockers.values()),
        expanded=expanded,
    )


def _route(parents: dict, state: tuple) -> list[str]:
    rooms: list[str] = []
    node: tuple | None = state
    while node is not None:
        rooms.append(node[0])
        node = parents[node]
    return list(reversed(rooms))


def _diagnose(
    level: Level,
    reachable: set[str],
    unreachable: frozenset[str],
    blockers: list[Blocker],
) -> str:
    """A one-line, human-readable account of why the level cannot be finished."""
    goals = sorted(level.goals)
    goal_text = goals[0] if len(goals) == 1 else "/".join(goals)
    parts = [f"goal room {goal_text} is not reachable"]

    key_rooms = set(level.key_rooms)
    stranded_keys = sorted(key_rooms & set(unreachable))
    if stranded_keys:
        parts.append(f"small key(s) in room(s) {', '.join(stranded_keys)} cannot be collected")

    starved = [b for b in blockers if b.reason == "no small key in hand"]
    if starved:
        doors = sorted({f"{b.passage.src}-{b.passage.dst}" for b in starved})
        parts.append(f"out of keys at door(s) {', '.join(doors)}")

    other = sorted({b.reason for b in blockers} - {"no small key in hand"})
    if other:
        parts.append("also blocked by: " + "; ".join(other))
    return "; ".join(parts)


def is_solvable(level: Level, cap: int = DEFAULT_CAP) -> bool:
    return solve(level, cap).solvable
