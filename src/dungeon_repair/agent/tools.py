"""Tools the agent can call.

The solver has already settled correctness: every repair in ``repair_options``
is verified to make the level winnable. So these tools are not there to find a
fix, they are there to tell the difference between a hundred fixes that all
work -- how far apart the rooms are, what the change does to the key economy,
whether it rewrites the topology or leaves the floor plan alone.

``compare`` accepts edits that are *not* in the verified set as well, and says
so plainly. An agent that wants to check its own idea should be able to.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..candidates import CandidateSet, verified_candidates
from ..memory import DesignMemory
from ..route import forced, touches_keys
from ..edits import ADD_DOOR, ADD_KEY, Edit, KINDS, MOVE_KEY, UNLOCK, parse_edit
from ..level import KEY_LOCKED, Level, SMALL_KEY, describe_passage, describe_room
from ..solver import solve
from ..topology import distances_from

MAX_LISTED = 60
MAX_COMPARED = 8


class ToolError(Exception):
    """Bad arguments from the model. Reported back to it as feedback, not raised."""


@dataclass
class Submission:
    edit: Edit
    reason: str


@dataclass
class Hypothesis:
    """A commitment about what went wrong, made before options are visible."""

    repair_kind: str
    rooms: list[str]
    reasoning: str

    def to_json(self) -> dict:
        return {
            "repair_kind": self.repair_kind,
            "rooms": self.rooms,
            "reasoning": self.reasoning,
        }


def _fmt_edit(edit: Edit) -> str:
    return f"{edit.kind}(a={edit.a}" + (f", b={edit.b})" if edit.b else ")")


class Toolbox:
    """Tools bound to one broken level and its verified candidate set."""

    def __init__(
        self,
        level: Level,
        candidates: CandidateSet | None = None,
        require_hypothesis: bool = False,
        memory: DesignMemory | None = None,
        signal_shape: bool = False,
    ):
        #: Surface what the shape of the verified set already rules out. Off by
        #: default so the shipped headline stays reproducible.
        self.signal_shape = signal_shape
        #: Motifs mined from the designer's *other* dungeons. Optional, and
        #: never consulted for correctness -- it annotates options and answers
        #: `design_rhythm`, which is the one question the other tools cannot.
        self.memory = memory
        #: When True, `repair_options`, `compare` and `submit` refuse until the
        #: agent has committed to a hypothesis. Off by default: it makes the
        #: agent more principled and, measurably, slightly less accurate --
        #: see Stage 14 in docs/CHANGELOG.md. Kept so the arm stays reproducible.
        self.require_hypothesis = require_hypothesis
        self.level = level
        self.candidates = candidates or verified_candidates(level)
        self.verified = set(self.candidates.verified)
        self.diagnosis = solve(level)
        self.submission: Submission | None = None
        #: What the agent expects the bug to be, committed before it may look
        #: at any repair option. `first_hypothesis` is locked at the first call
        #: and is what gets scored -- revision is allowed, but the score
        #: reflects what it believed before it saw the menu.
        self.first_hypothesis: Hypothesis | None = None
        self.hypothesis: Hypothesis | None = None
        self._distances = {
            room: distances_from(level, room) for room in level.rooms
        }

    @property
    def rhythm_available(self) -> bool:
        """Is the design memory of any possible use on this case?

        The motifs are about where a small key sits. When no key edit verifies,
        no key was displaced, so the tool cannot inform the answer -- and two
        runs showed it costing accuracy on exactly those cases while helping
        elsewhere. Offering a tool that cannot apply is not neutral.
        """
        return bool(self.memory) and touches_keys(self.candidates)

    # -- schemas ------------------------------------------------------------
    def schemas(self) -> list[dict]:
        rooms = "a room id, as a string"
        gated = (
            [
                _tool(
                    "hypothesise",
                    "Commit to what you think went wrong, before you look at any "
                    "repair options. Required before repair_options, compare or "
                    "submit will answer. You may revise it later.",
                    {
                        "repair_kind": {
                            "type": "string",
                            "enum": list(KINDS),
                            "description": "The kind of repair you expect to make.",
                        },
                        "rooms": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The room(s) or door endpoints involved.",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "What in the diagnosis points at this bug.",
                        },
                    },
                    required=["repair_kind", "rooms", "reasoning"],
                )
            ]
            if self.require_hypothesis
            else []
        )
        return [
            _tool(
                "diagnose",
                "Explain why the dungeon cannot currently be finished: which "
                "rooms are unreachable and which doors block progress.",
                {},
            ),
            *gated,
            _tool(
                "repair_options",
                "List repairs that are already verified to make the dungeon "
                "winnable. Every option returned is provably correct; the "
                "question is which one a designer would accept. Filter to keep "
                "the list short.",
                {
                    "kind": {
                        "type": "string",
                        "enum": list(KINDS),
                        "description": "Only options of this kind.",
                    },
                    "involving_room": {
                        "type": "string",
                        "description": f"Only options that touch this room ({rooms}).",
                    },
                    "within_hops_of": {
                        "type": "string",
                        "description": (
                            "Only options whose rooms are close to this room, "
                            "measured in doors traversed ignoring locks."
                        ),
                    },
                    "max_hops": {
                        "type": "integer",
                        "description": "Hop limit for within_hops_of. Default 3.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"Maximum options to return (<= {MAX_LISTED}).",
                    },
                },
            ),
            _tool(
                "compare",
                "Analyse specific repairs side by side: how far apart the rooms "
                "are, what happens to the key economy, whether the topology "
                "changes, and how the winning route changes.",
                {
                    "options": {
                        "type": "array",
                        "description": f"Up to {MAX_COMPARED} repairs to compare.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": list(KINDS)},
                                "a": {"type": "string"},
                                "b": {"type": "string"},
                            },
                            "required": ["kind", "a"],
                        },
                    }
                },
                required=["options"],
            ),
            *(
                [
                    _tool(
                        "design_rhythm",
                        "What the same designers' other dungeons do: where small "
                        "keys tend to sit, and how strong each tendency actually "
                        "is. Measured with this dungeon held out.",
                        {},
                    )
                ]
                if self.rhythm_available
                else []
            ),
            _tool(
                "room_detail",
                "Look up specific rooms: contents, every door on them, and how "
                "far they sit from the start.",
                {
                    "rooms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Room ids to describe.",
                    }
                },
                required=["rooms"],
            ),
            _tool(
                "submit",
                "Submit the repair to apply, with the reasoning a designer "
                "would want to read. Rejected unless the repair is verified.",
                {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                    "reason": {
                        "type": "string",
                        "description": "Why this repair over the other verified ones.",
                    },
                },
                required=["kind", "a", "reason"],
            ),
        ]

    # -- dispatch -----------------------------------------------------------
    def call(self, name: str, arguments: dict) -> str:
        handler = {
            "diagnose": self.diagnose_tool,
            "hypothesise": self.hypothesise,
            "repair_options": self.repair_options,
            "compare": self.compare,
            "design_rhythm": self.design_rhythm,
            "room_detail": self.room_detail,
            "submit": self.submit,
        }.get(name)
        if handler is None:
            raise ToolError(f"no such tool: {name!r}")
        return handler(**_clean(arguments))

    # -- implementations ----------------------------------------------------
    def diagnose_tool(self) -> str:
        d = self.diagnosis
        lines = [f"Winnable: {'yes' if d.solvable else 'no'}"]
        if d.solvable:
            return lines[0] + " (nothing to repair)"
        lines.append(f"Why: {d.reason}")
        lines.append(
            f"Reachable rooms ({len(d.reachable)}): "
            f"{', '.join(sorted(d.reachable, key=_room_key))}"
        )
        if d.unreachable:
            lines.append(
                f"Unreachable rooms ({len(d.unreachable)}): "
                f"{', '.join(sorted(d.unreachable, key=_room_key))}"
            )
        if d.blockers:
            lines.append("Doors reached but never passable:")
            for blocker in sorted(d.blockers, key=lambda b: (b.passage.src, b.passage.dst)):
                lines.append(f"  {blocker}")
        keys = len(self.level.key_rooms)
        key_doors = sum(
            1 for door in self.level.doors()
            if any(KEY_LOCKED in p.requires for p in self.level.passages_of(door))
        )
        lines.append(f"Key economy: {keys} small key(s) for {key_doors} key-locked door(s)")
        lines.extend(self._candidate_shape())
        return "\n".join(lines)

    def _candidate_shape(self) -> list[str]:
        """What the shape of the verified set already rules out.

        Both facts are properties of the candidate set, not hints at an answer:
        they say which corruptions are *impossible*, which the option list
        implies but never states. Measured on the 77-case set, the first is
        right 30 times in 31 and the second 21 in 23.
        """
        if not self.signal_shape:
            return []
        # The doors-only note ("this must be a dropped corridor") was measured
        # and removed. It was true, and it cost accuracy on exactly the cases it
        # described: 9 -> 7, 6, 7 across three runs. Handing the agent the
        # conclusion appears to stop it doing the work that produced the
        # conclusion. Only the sole-unlock note survives.
        out = []
        decided, _ = forced(self.candidates)
        if decided is not None:
            out.append(
                f"Note: the key economy is repairable, yet exactly one door can be "
                f"unlocked -- {_fmt_edit(decided)}. A dropped corridor cannot leave "
                f"that shape, so a lock was most likely added that should not exist."
            )
        return out

    def design_rhythm(self) -> str:
        if not self.rhythm_available:
            raise ToolError(
                "no design memory applies here: no key edit repairs this level, "
                "so no key was displaced"
            )
        return self.memory.summary()

    def hypothesise(self, repair_kind: str, rooms: list[str], reasoning: str) -> str:
        if repair_kind not in KINDS:
            raise ToolError(
                f"unknown repair_kind {repair_kind!r}; expected one of {', '.join(KINDS)}"
            )
        if not str(reasoning).strip():
            raise ToolError("hypothesise needs the reasoning behind the guess.")
        unknown = [r for r in rooms if r not in self.level.rooms]
        if unknown:
            raise ToolError(f"no such room(s): {', '.join(unknown)}")
        made = Hypothesis(repair_kind, [str(r) for r in rooms], str(reasoning).strip())
        self.hypothesis = made
        if self.first_hypothesis is None:
            self.first_hypothesis = made
            return (
                f"Recorded: you expect a {repair_kind} involving "
                f"{', '.join(made.rooms) or '(no rooms named)'}. "
                "repair_options, compare and submit are now available."
            )
        return f"Revised to {repair_kind} involving {', '.join(made.rooms)}."

    def _require_hypothesis(self, tool: str) -> None:
        if self.require_hypothesis and self.first_hypothesis is None:
            raise ToolError(
                f"call hypothesise before {tool}: commit to what you think broke "
                "the dungeon before looking at the repairs that are available."
            )

    def repair_options(
        self,
        kind: str | None = None,
        involving_room: str | None = None,
        within_hops_of: str | None = None,
        max_hops: int = 3,
        limit: int = 25,
    ) -> str:
        self._require_hypothesis("repair_options")
        if kind is not None and kind not in KINDS:
            raise ToolError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
        for room in (involving_room, within_hops_of):
            if room is not None and room not in self.level.rooms:
                raise ToolError(f"no such room: {room!r}")

        limit = max(1, min(int(limit), MAX_LISTED))
        options = list(self.candidates.verified)
        if kind:
            options = [e for e in options if e.kind == kind]
        if involving_room:
            options = [e for e in options if involving_room in (e.a, e.b)]
        if within_hops_of:
            near = self._distances[within_hops_of]
            options = [
                e for e in options
                if all(near.get(r, 99) <= max_hops for r in (e.a, e.b) if r)
            ]

        counts = self.candidates.counts()
        header = (
            f"{len(self.candidates)} verified repairs in total "
            f"({', '.join(f'{k}: {v}' for k, v in counts.items() if v)}). "
            f"{len(options)} match this filter"
        )
        if not options:
            return header + ". Try a wider filter."

        # Take a balanced sample across kinds rather than the first N in
        # enumeration order. Enumeration is ordered least-invasive-first for
        # the deterministic baseline's benefit; reusing that order here meant
        # truncation could hide every alternative behind a wall of unlocks.
        # This list is a sample, not a ranking, and says so.
        shown = _round_robin(options)[:limit] if kind is None else options[:limit]
        lines = [
            header
            + f"; showing {len(shown)}"
            + (" (balanced across kinds, not ranked)" if kind is None else "")
            + ":"
        ]
        for edit in shown:
            lines.append(
                f"  {_fmt_edit(edit):<34} {edit.describe()}"
                f"{self._caveat(edit)}{self._rhythm(edit)}"
            )
        if len(options) > len(shown):
            lines.append(
                f"  ... {len(options) - len(shown)} more not shown -- narrow with "
                f"kind, involving_room, or within_hops_of"
            )
        return "\n".join(lines)

    def _caveat(self, edit: Edit) -> str:
        """Say what an unlock would actually destroy.

        `unlock` clears every requirement on a door, not just a small-key lock.
        On a door that is impassable, boss-key-locked or key-item-locked that
        means demolishing something the designer built on purpose, and nothing
        in the option's name says so.
        """
        if edit.kind != UNLOCK:
            return ""
        requirements: set[str] = set()
        for passage in self.level.passages_of(edit.door):
            requirements |= set(passage.requires)
        beyond = requirements - {KEY_LOCKED}
        if not beyond:
            return ""
        return f"  [WARNING: this door is {describe_passage(beyond)} -- unlocking removes that]"

    def _rhythm(self, edit: Edit) -> str:
        """How the destination room matches the designer's habits.

        Only for `move_key`: the motifs are about where a key sits, and
        attaching them to a door edit would be dressing noise up as evidence.
        """
        if not self.memory or edit.kind != MOVE_KEY or not edit.b:
            return ""
        return self.memory.annotate(self.level, edit.b)

    def compare(self, options: list[dict]) -> str:
        self._require_hypothesis("compare")
        if not options:
            raise ToolError("compare needs at least one option")
        if len(options) > MAX_COMPARED:
            raise ToolError(f"compare takes at most {MAX_COMPARED} options at a time")

        blocks = []
        for raw in options:
            edit = self._parse(raw)
            blocks.append(self._analyse(edit))
        return "\n\n".join(blocks)

    def room_detail(self, rooms: list[str]) -> str:
        if not rooms:
            raise ToolError("room_detail needs at least one room")
        unknown = [r for r in rooms if r not in self.level.rooms]
        if unknown:
            raise ToolError(f"no such room(s): {', '.join(unknown)}")

        start = self.level.start
        from_start = self._distances.get(start, {}) if start else {}
        lines = []
        for room in rooms:
            distance = from_start.get(room)
            reach = "reachable" if room in self.diagnosis.reachable else "UNREACHABLE"
            lines.append(
                f"room {room}: {describe_room(self.level.rooms[room])} "
                f"[{reach}, {distance if distance is not None else 'no'} hops from start]"
            )
            for passage in sorted(
                (p for p in self.level.passages if p.src == room),
                key=lambda p: _room_key(p.dst),
            ):
                lines.append(
                    f"    -> {passage.dst}: {describe_passage(passage.requires)}"
                )
        return "\n".join(lines)

    def submit(self, kind: str, a: str, reason: str = "", b: str = "") -> str:
        self._require_hypothesis("submit")
        edit = self._parse({"kind": kind, "a": a, "b": b})
        if edit not in self.verified:
            raise ToolError(
                f"{_fmt_edit(edit)} is not a verified repair -- applying it leaves "
                "the dungeon unwinnable. Choose one of the options from "
                "repair_options."
            )
        if not reason.strip():
            raise ToolError("submit needs a reason a designer can read.")
        self.submission = Submission(edit, reason.strip())
        return f"Submitted {_fmt_edit(edit)}."

    # -- internals ----------------------------------------------------------
    def _parse(self, raw: dict) -> Edit:
        kind = str(raw.get("kind", "")).strip()
        if kind not in KINDS:
            raise ToolError(f"unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
        a, b = str(raw.get("a", "")).strip(), str(raw.get("b", "") or "").strip()
        if a not in self.level.rooms:
            raise ToolError(f"no such room: {a!r}")
        if kind in (MOVE_KEY, UNLOCK, ADD_DOOR):
            if not b:
                raise ToolError(f"{kind} needs both rooms a and b")
            if b not in self.level.rooms:
                raise ToolError(f"no such room: {b!r}")
        if kind == MOVE_KEY and SMALL_KEY not in self.level.rooms[a]:
            raise ToolError(f"room {a} holds no small key to move")
        if kind == ADD_KEY and SMALL_KEY in self.level.rooms[a]:
            raise ToolError(f"room {a} already holds a small key")
        return parse_edit(kind, a, b)

    def _analyse(self, edit: Edit) -> str:
        repaired = edit.apply(self.level)
        result = solve(repaired)
        valid = edit in self.verified
        lines = [f"{_fmt_edit(edit)} -- {edit.describe()}"]
        lines.append(
            f"  verified: {'yes' if valid else 'NO - this does not make the dungeon winnable'}"
        )

        if edit.b:
            hops = self._distances.get(edit.a, {}).get(edit.b)
            lines.append(
                f"  rooms {edit.a} and {edit.b} are "
                + (f"{hops} door(s) apart" if hops is not None else "not connected at all")
                + " in the broken dungeon"
            )
        if edit.kind == ADD_DOOR:
            lines.append("  topology: adds a corridor that did not exist before")
        elif edit.kind == UNLOCK:
            was = {
                describe_passage(p.requires)
                for p in self.level.passages_of(edit.door)
            }
            lines.append(f"  topology: unchanged; door was {'/'.join(sorted(was))}")
        else:
            lines.append("  topology: unchanged")

        keys_before = len(self.level.key_rooms)
        keys_after = len(repaired.key_rooms)
        locked_after = sum(
            1 for door in repaired.doors()
            if any(KEY_LOCKED in p.requires for p in repaired.passages_of(door))
        )
        lines.append(
            f"  key economy after: {keys_after} key(s) for {locked_after} key-locked "
            f"door(s) (was {keys_before} keys)"
        )
        if self.memory and edit.kind == MOVE_KEY and edit.b:
            found = self.memory.matches(self.level, edit.b)
            lines.append(
                f"  room {edit.b} vs the designer's habits: "
                + ("; ".join(found) if found else "matches none of the measured motifs")
            )
        if result.solvable:
            lines.append(
                f"  winning route: {len(result.route)} rooms, "
                f"{' -> '.join(result.route[:12])}"
                + (" ..." if len(result.route) > 12 else "")
            )
            newly = len(result.reachable) - len(self.diagnosis.reachable)
            lines.append(f"  rooms newly reachable: {newly}")
        else:
            lines.append(f"  still broken: {result.reason}")
        return "\n".join(lines)


def _round_robin(edits: list[Edit]) -> list[Edit]:
    """Interleave edits by kind so no single kind can crowd out the rest."""
    buckets: dict[str, list[Edit]] = {}
    for edit in edits:
        buckets.setdefault(edit.kind, []).append(edit)
    order = [k for k in KINDS if k in buckets]
    out: list[Edit] = []
    index = 0
    while len(out) < len(edits):
        for kind in order:
            bucket = buckets[kind]
            if index < len(bucket):
                out.append(bucket[index])
        index += 1
    return out


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


def _clean(arguments: dict) -> dict:
    """Drop nulls so optional parameters fall back to their defaults."""
    return {k: v for k, v in (arguments or {}).items() if v is not None}


def _room_key(room: str) -> tuple[int, object]:
    return (0, int(room)) if room.isdigit() else (1, room)
