"""The edit vocabulary.

Every repair, every corruption, and every candidate the agent may choose is
one of these four single edits. Keeping one vocabulary for all three means a
seeded corruption's inverse is expressible as a candidate, which is what makes
intent recovery measurable rather than a matter of taste.
"""

from __future__ import annotations

from dataclasses import dataclass

from .level import SMALL_KEY, Level

MOVE_KEY = "move_key"
ADD_KEY = "add_key"
UNLOCK = "unlock"
ADD_DOOR = "add_door"

KINDS = (MOVE_KEY, ADD_KEY, UNLOCK, ADD_DOOR)


@dataclass(frozen=True, order=True)
class Edit:
    """A single change to a level.

    ``move_key``  -- move a small key from room ``a`` to room ``b``
    ``add_key``   -- place a new small key in room ``a``
    ``unlock``    -- clear every requirement from the door ``a``--``b``
    ``add_door``  -- add an open two-way passage between ``a`` and ``b``
    """

    kind: str
    a: str
    b: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown edit kind: {self.kind!r}")
        # Doors are undirected, so canonicalise the endpoint order. Without
        # this, unlock(3,5) and unlock(5,3) would count as different answers.
        if self.kind in (UNLOCK, ADD_DOOR) and self.b < self.a:
            low, high = self.b, self.a
            object.__setattr__(self, "a", low)
            object.__setattr__(self, "b", high)

    @property
    def door(self) -> tuple[str, str]:
        return (self.a, self.b)

    def apply(self, level: Level) -> Level:
        if self.kind == MOVE_KEY:
            return level.moved(SMALL_KEY, self.a, self.b)
        if self.kind == ADD_KEY:
            return level.with_symbol_added(SMALL_KEY, self.a)
        if self.kind == UNLOCK:
            return level.with_door_requirements(self.door, frozenset())
        return level.with_door_added(self.a, self.b)

    def describe(self) -> str:
        if self.kind == MOVE_KEY:
            return f"move the small key in room {self.a} to room {self.b}"
        if self.kind == ADD_KEY:
            return f"place an extra small key in room {self.a}"
        if self.kind == UNLOCK:
            return f"remove the lock on the door between rooms {self.a} and {self.b}"
        return f"open a new passage between rooms {self.a} and {self.b}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "a": self.a, "b": self.b}

    @classmethod
    def from_json(cls, data: dict) -> "Edit":
        return cls(data["kind"], str(data["a"]), str(data.get("b") or ""))

    def __str__(self) -> str:
        return f"{self.kind}({self.a}{',' + self.b if self.b else ''})"


def parse_edit(kind: str, a: str, b: str = "") -> Edit:
    """Build an Edit from loosely-typed input (tool calls, CLI arguments)."""
    return Edit(str(kind).strip(), str(a).strip(), str(b or "").strip())
