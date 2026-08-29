"""Trajectory recording.

Every model call and every tool call is appended to a JSONL trace as it
happens. Traces are a submission deliverable, so they are captured by the code
that does the work rather than reconstructed afterwards from logs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Trace:
    """An append-only record of one run of one agent on one case."""

    run_id: str
    case_id: str
    method: str
    path: Path | None = None
    events: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.perf_counter)

    def event(self, kind: str, **payload: Any) -> None:
        self.record({"kind": kind, **payload})

    def record(self, fields: dict) -> None:
        entry = {"t": round(time.perf_counter() - self.started, 3), **fields}
        self.events.append(entry)
        if self.path is not None:
            with self.path.open("a") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")

    # -- convenience wrappers, one per thing worth seeing in a trajectory ---
    def instructions(self, system: str, user: str) -> None:
        self.event("instructions", system=system, user=user)

    def model_message(self, text: str, tool_calls: list[dict], usage: dict) -> None:
        self.event("model", text=text, tool_calls=tool_calls, usage=usage)

    def tool_call(self, name: str, arguments: dict) -> None:
        self.event("tool_call", name=name, arguments=arguments)

    def tool_result(self, name: str, result: str, ok: bool = True) -> None:
        self.event("tool_result", name=name, ok=ok, result=result)

    def feedback(self, message: str) -> None:
        """Rejection sent back to the model -- an invalid edit, a bad argument."""
        self.event("feedback", message=message)

    def checkpoint(self, question: str, answer: str, automatic: bool) -> None:
        self.event(
            "human_checkpoint", question=question, answer=answer, automatic=automatic
        )

    def finish(self, **payload: Any) -> None:
        # Nested rather than splatted: a scored attempt has its own "kind"
        # field, which would collide with the event's.
        self.record({"kind": "finish", "result": payload})


def open_trace(directory: str | Path, run_id: str, case_id: str, method: str) -> Trace:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    safe = case_id.replace("#", "_").replace("/", "_")
    path = directory / f"{method}__{safe}.jsonl"
    path.write_text("")  # truncate any earlier run of the same case
    return Trace(run_id=run_id, case_id=case_id, method=method, path=path)


def render_markdown(path: str | Path) -> str:
    """Turn a JSONL trace into something a human (or a judge) can read."""
    path = Path(path)
    lines = [f"# Trajectory: {path.stem}", ""]
    for raw in path.read_text().splitlines():
        if not raw.strip():
            continue
        e = json.loads(raw)
        kind, t = e["kind"], e["t"]
        if kind == "instructions":
            lines += [f"## t={t}s  instructions", "", "**System prompt**", "",
                      "```", e["system"].strip(), "```", "",
                      "**Task**", "", "```", e["user"].strip(), "```", ""]
        elif kind == "model":
            usage = e.get("usage") or {}
            lines += [f"## t={t}s  model turn "
                      f"({usage.get('input_tokens', '?')} in / "
                      f"{usage.get('output_tokens', '?')} out)", ""]
            if e.get("text"):
                lines += [e["text"].strip(), ""]
            for call in e.get("tool_calls") or []:
                lines += [f"- calls `{call['name']}({json.dumps(call['arguments'])})`"]
            lines.append("")
        elif kind == "tool_call":
            lines += [f"### t={t}s  tool call `{e['name']}`", "",
                      "```json", json.dumps(e["arguments"], indent=2), "```", ""]
        elif kind == "tool_result":
            status = "" if e.get("ok", True) else " (rejected)"
            lines += [f"### t={t}s  tool result `{e['name']}`{status}", "",
                      "```", str(e["result"]).strip()[:4000], "```", ""]
        elif kind == "feedback":
            lines += [f"### t={t}s  feedback to model", "", f"> {e['message']}", ""]
        elif kind == "human_checkpoint":
            mode = "auto-approved" if e.get("automatic") else "human"
            lines += [f"### t={t}s  human checkpoint ({mode})", "",
                      f"**{e['question']}**", "", f"-> {e['answer']}", ""]
        elif kind == "finish":
            payload = e.get("result", {})
            lines += [f"## t={t}s  finished", "",
                      "```json", json.dumps(payload, indent=2, default=str), "```", ""]
    return "\n".join(lines)
