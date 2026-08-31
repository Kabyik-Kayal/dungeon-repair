"""The agent loop: model, tools, verification, human checkpoint.

Three properties this loop is built to guarantee:

* It cannot ship an unplayable level. ``submit`` refuses any edit the solver
  has not verified, and the refusal goes back to the model as feedback.
* Everything is recorded as it happens -- instructions, tool calls, tool
  results, rejections, retries -- because trajectories are a deliverable.
* Nothing is applied without a checkpoint. Interactive runs ask a human;
  evaluation runs auto-approve and the trace records which of the two it was.
"""

from __future__ import annotations

import json
import time
from typing import Callable

from ..candidates import CandidateSet
from ..corrupt import Case
from ..llm import Client
from ..memory import DesignMemory
from ..metrics import Attempt, score
from ..trace import Trace
from .prompts import CHECKPOINT, DIAGNOSE_FIRST, NUDGE, RHYTHM, SYSTEM, TASK
from .tools import Toolbox, ToolError

METHOD = "agent"
MAX_STEPS = 12


def run(
    case: Case,
    client: Client | None = None,
    trace: Trace | None = None,
    candidates: CandidateSet | None = None,
    max_steps: int = MAX_STEPS,
    approve: Callable[[str], bool] | None = None,
    diagnose_first: bool = False,
    route: bool = False,
    memory: DesignMemory | None = None,
    **_: object,
) -> Attempt:
    client = client or Client()
    started = time.perf_counter()
    toolbox = Toolbox(
        case.broken,
        candidates,
        require_hypothesis=diagnose_first,
        memory=memory,
        signal_shape=route,
    )
    system = SYSTEM + DIAGNOSE_FIRST if diagnose_first else SYSTEM
    if toolbox.rhythm_available:
        system += RHYTHM
    task = TASK.format(outline=case.broken.outline())
    if trace:
        trace.instructions(system, task)

    messages: list[dict] = [{"role": "user", "content": task}]
    schemas = toolbox.schemas()
    error, steps, nudged = "", 0, False

    try:
        while steps < max_steps and toolbox.submission is None:
            steps += 1
            reply = client.complete(messages, tools=schemas, system=system)
            if trace:
                trace.model_message(
                    reply.text,
                    reply.tool_calls,
                    {
                        "input_tokens": reply.input_tokens,
                        "output_tokens": reply.output_tokens,
                    },
                )
            messages.append(_assistant_message(reply))

            if not reply.tool_calls:
                if nudged:
                    error = "model stopped without submitting a repair"
                    break
                nudged = True
                messages.append({"role": "user", "content": NUDGE})
                if trace:
                    trace.feedback(NUDGE)
                continue

            for call in reply.tool_calls:
                if trace:
                    trace.tool_call(call["name"], call["arguments"])
                try:
                    result, ok = toolbox.call(call["name"], call["arguments"]), True
                except ToolError as exc:
                    result, ok = f"Rejected: {exc}", False
                if trace:
                    trace.tool_result(call["name"], result, ok=ok)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "content": result,
                    }
                )
        else:
            if toolbox.submission is None and not error:
                error = f"no repair submitted within {max_steps} steps"
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        error = f"{type(exc).__name__}: {exc}"

    submission = toolbox.submission
    edit = submission.edit if submission else None
    rationale = submission.reason if submission else ""

    if edit is not None:
        question = CHECKPOINT.format(level=case.broken.id)
        automatic = approve is None
        accepted = True if automatic else approve(
            f"{question}\n\n  {edit.describe()}\n\n  {rationale}\n"
        )
        if trace:
            trace.checkpoint(question, "approved" if accepted else "rejected", automatic)
        if not accepted:
            edit, error = None, "repair declined at the human checkpoint"

    attempt = score(
        case,
        METHOD,
        edit,
        time.perf_counter() - started,
        usage=client.usage.to_json(),
        rationale=rationale,
        error=error,
        extra={
            "steps": steps,
            "diagnose_first": diagnose_first,
            "route": route,
            "memory": bool(memory),
            "decided_by": "agent",
            "verified_options": len(toolbox.candidates),
            "enumeration_seconds": round(toolbox.candidates.seconds, 3),
            # What it believed before it saw a single repair option. Scored
            # separately from the answer: diagnosing right and repairing right
            # are different failures.
            "hypothesis": (
                toolbox.first_hypothesis.to_json()
                if toolbox.first_hypothesis
                else None
            ),
            "revised_hypothesis": (
                toolbox.hypothesis.to_json()
                if toolbox.hypothesis
                and toolbox.hypothesis is not toolbox.first_hypothesis
                else None
            ),
        },
    )
    if trace:
        trace.finish(**attempt.to_json())
    return attempt


def _assistant_message(reply) -> dict:
    """Rebuild the assistant turn in provider-neutral form for the next request."""
    message: dict = {"role": "assistant", "content": reply.text or ""}
    if reply.tool_calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"]),
                },
            }
            for call in reply.tool_calls
        ]
    return message
