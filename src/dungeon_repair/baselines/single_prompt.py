"""Baseline 2: one model call, no tools, no solver.

The level goes in, a repair comes out. Nothing verifies it, so this is the
only method in the comparison that can ship a level that still cannot be
finished -- which is the point of including it. It measures what a capable
model does unaided on exactly the same task.
"""

from __future__ import annotations

import time

from ..corrupt import KIND_STORY, Case
from ..edits import KINDS, parse_edit
from ..llm import Client, extract_json_object
from ..metrics import Attempt, score
from ..trace import Trace

METHOD = "single_prompt"

SYSTEM = """You are a level designer reviewing a procedurally generated dungeon \
that cannot be completed.

The dungeon is a graph. Rooms hold contents (start, goal, small keys, the boss \
key, a key item). Doors between rooms may be open, key-locked (costs one small \
key, which is consumed), boss-key-locked, key-item-locked, soft-locked (still \
passable), bombable (still passable), or impassable.

Exactly one thing was changed by a buggy generation step, and that one change \
made the dungeon unwinnable. Work out what was changed, and propose the single \
edit that undoes it.

Reply with one JSON object and nothing else:
{"kind": "<move_key|add_key|unlock|add_door>", "a": "<room>", "b": "<room or empty>", \
"why": "<one or two sentences>"}

  move_key  - move the small key in room a to room b
  add_key   - place an extra small key in room a
  unlock    - remove the lock on the door between rooms a and b
  add_door  - open a new passage between rooms a and b"""


def build_prompt(case: Case) -> str:
    return (
        f"{case.broken.outline()}\n\n"
        "This dungeon cannot currently be finished. Propose the single edit that "
        "restores the designer's intent."
    )


def run(
    case: Case,
    client: Client | None = None,
    trace: Trace | None = None,
    **_: object,
) -> Attempt:
    client = client or Client()
    prompt = build_prompt(case)
    if trace:
        trace.instructions(SYSTEM, prompt)

    started = time.perf_counter()
    error, edit, rationale = "", None, ""
    try:
        reply = client.complete([{"role": "user", "content": prompt}], system=SYSTEM)
        if trace:
            trace.model_message(
                reply.text,
                [],
                {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens},
            )
        parsed = extract_json_object(reply.text)
        if parsed is None:
            error = "model reply contained no JSON object"
        elif parsed.get("kind") not in KINDS:
            error = f"unknown edit kind: {parsed.get('kind')!r}"
        else:
            rooms = case.broken.rooms
            a, b = str(parsed.get("a", "")), str(parsed.get("b", "") or "")
            if a not in rooms or (b and b not in rooms):
                error = f"edit names a room that does not exist: {a!r}/{b!r}"
            else:
                edit = parse_edit(parsed["kind"], a, b)
                rationale = str(parsed.get("why", ""))
    except Exception as exc:  # noqa: BLE001 - recorded, never silently dropped
        error = f"{type(exc).__name__}: {exc}"

    seconds = time.perf_counter() - started
    attempt = score(
        case,
        METHOD,
        edit,
        seconds,
        usage=client.usage.to_json(),
        rationale=rationale,
        error=error,
    )
    if trace:
        trace.finish(**attempt.to_json())
    return attempt
