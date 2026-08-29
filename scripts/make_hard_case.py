"""Build the deliberately hard evaluation case: "Spiral Keep".

Every other case in the set is a real shipped dungeon with a seeded mutation.
This one is authored so that the *kind* of bug is easy and the *choice* is not.

The keep is a chain of three key-locked gates. Before each gate sits an alcove
holding exactly the key that opens it -- a rhythm the dungeon repeats three
times. The bug drops the third key into the alcove behind its own gate, so the
player runs out of keys one gate short.

Dozens of edits repair that. Unlock any of the three gates. Drop a spare key
in any reachable room. Cut a new corridor past the gate. Move the stranded key
to any room the player can reach -- and there are many. Only one repair keeps
the rhythm: put the key back in the alcove that was built for it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dungeon_repair.candidates import verified_candidates  # noqa: E402
from dungeon_repair.corrupt import Case, DISPLACED_KEY  # noqa: E402
from dungeon_repair.edits import Edit, MOVE_KEY  # noqa: E402
from dungeon_repair.level import Level, Passage  # noqa: E402
from dungeon_repair.solver import solve  # noqa: E402

OPEN: frozenset = frozenset()
KEY_DOOR = frozenset({"k"})
BOSS_DOOR = frozenset({"K"})

ROOMS = {
    "0": "s",       # gatehouse
    "1": "e",       # first hall
    "2": "e",       # second hall
    "3": "ep",      # third hall
    "4": "e",       # inner sanctum
    "5": "b",       # boss chamber
    "6": "t",       # treasury
    "10": "k",      # alcove before gate 1
    "11": "k",      # alcove before gate 2
    "12": "k",      # alcove before gate 3   <- the key this case displaces
    "13": "K",      # boss-key alcove, behind gate 3
    "14": "e",      # west wing
    "15": "p",      # west wing puzzle room
    "16": "e",      # east wing
    "17": "e",      # east wing dead end
    "18": "p",      # gallery off the second hall
}

DOORS = [
    ("0", "1", OPEN),
    ("1", "10", OPEN),
    ("1", "14", OPEN),
    ("14", "15", OPEN),
    ("1", "2", KEY_DOOR),      # gate 1
    ("2", "11", OPEN),
    ("2", "18", OPEN),
    ("2", "3", KEY_DOOR),      # gate 2
    ("3", "12", OPEN),
    ("3", "16", OPEN),
    ("16", "17", OPEN),
    ("3", "4", KEY_DOOR),      # gate 3
    ("4", "13", OPEN),
    ("4", "5", BOSS_DOOR),
    ("5", "6", OPEN),
]


def build() -> Level:
    passages = []
    for a, b, requires in DOORS:
        passages += [Passage(a, b, requires), Passage(b, a, requires)]
    return Level(
        id="spiral_keep",
        game="handmade",
        rooms={room: frozenset(contents) for room, contents in ROOMS.items()},
        passages=tuple(passages),
    )


def main() -> int:
    original = build()
    intact = solve(original)
    assert intact.solvable, f"the keep should be winnable as designed: {intact.reason}"

    # The bug: the third key generates inside the boss-key alcove, which sits
    # behind the very gate it opens.
    broken = original.moved("k", "12", "13")
    failure = solve(broken)
    assert not failure.solvable, "the corruption should make the keep unwinnable"

    truth = Edit(MOVE_KEY, "13", "12")
    assert solve(truth.apply(broken)).solvable

    case = Case(
        id="spiral_keep#hard",
        game="handmade",
        source_level="spiral_keep",
        kind=DISPLACED_KEY,
        broken=broken,
        original=original,
        truth=truth,
        note=(
            "Deliberately hard. The keep repeats one rhythm three times: an "
            "alcove holding the key for the gate directly ahead. The third key "
            "generated behind its own gate. Many repairs verify -- unlocking "
            "any gate, adding a spare key anywhere reachable, cutting a new "
            "corridor, or moving the stranded key to any reachable room. Only "
            "returning it to alcove 12 keeps the rhythm intact."
        ),
    )

    out = Path("eval/cases/spiral_keep_hard.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(case.to_json(), indent=2) + "\n")

    found = verified_candidates(broken)
    counts = ", ".join(f"{k}={v}" for k, v in found.counts().items() if v)
    print(f"wrote {out}")
    print(f"  winnable as designed:  {intact.summary()}")
    print(f"  after the bug:         {failure.reason}")
    print(f"  ground truth:          {truth} ({truth.describe()})")
    print(f"  verified repairs:      {len(found)} ({counts})")
    moves = [e for e in found.verified if e.kind == MOVE_KEY and e.a == "13"]
    print(f"  of which move the stranded key somewhere: {len(moves)} -- "
          f"exactly one of them is right")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
