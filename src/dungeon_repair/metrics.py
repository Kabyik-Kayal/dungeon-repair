"""Scoring one repair, and summarising a run.

Four numbers per case:

* **solvable** -- does the repaired level actually verify. A gate, not an
  achievement: any method with solver access clears it by construction.
* **intent recovery** -- did the chosen repair match the edit that broke the
  level. This is the primary metric, and it is objective only because the
  corruption was seeded.
* **layout preservation** -- how much of the designer's original structure
  survives. Separates a single edit from regenerating the dungeon.
* **cost and wall time** -- what the answer took.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from .corrupt import Case
from .edits import Edit
from .level import Level
from .solver import solve
from .topology import layout_preservation


@dataclass
class Attempt:
    """One method's answer on one case, already scored."""

    case_id: str
    method: str
    kind: str
    edit: Edit | None
    solvable: bool
    intent_hit: bool
    layout: float
    seconds: float
    usage: dict = field(default_factory=dict)
    rationale: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "method": self.method,
            "kind": self.kind,
            "edit": self.edit.to_json() if self.edit else None,
            "solvable": self.solvable,
            "intent_hit": self.intent_hit,
            "layout": round(self.layout, 4),
            "seconds": round(self.seconds, 3),
            "usage": self.usage,
            "rationale": self.rationale,
            "error": self.error,
            "extra": self.extra,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Attempt":
        return cls(
            case_id=data["case_id"],
            method=data["method"],
            kind=data.get("kind", ""),
            edit=Edit.from_json(data["edit"]) if data.get("edit") else None,
            solvable=data["solvable"],
            intent_hit=data["intent_hit"],
            layout=data["layout"],
            seconds=data["seconds"],
            usage=data.get("usage", {}),
            rationale=data.get("rationale", ""),
            error=data.get("error", ""),
            extra=data.get("extra", {}),
        )


def score(
    case: Case,
    method: str,
    edit: Edit | None,
    seconds: float,
    repaired: Level | None = None,
    usage: dict | None = None,
    rationale: str = "",
    error: str = "",
    extra: dict | None = None,
) -> Attempt:
    """Score an answer against the case's known ground truth.

    ``repaired`` is for methods that do not express their answer as a single
    edit -- regeneration hands back a whole level instead.
    """
    if repaired is None:
        repaired = edit.apply(case.broken) if edit else case.broken
    solvable = solve(repaired).solvable
    return Attempt(
        case_id=case.id,
        method=method,
        kind=case.kind,
        edit=edit,
        solvable=solvable,
        intent_hit=bool(edit is not None and edit == case.truth),
        layout=layout_preservation(case.original, repaired),
        seconds=seconds,
        usage=usage or {},
        rationale=rationale,
        error=error,
        extra=extra or {},
    )


def summarise(attempts: list[Attempt]) -> dict:
    if not attempts:
        return {}
    n = len(attempts)
    costs = [a.usage.get("cost_usd") for a in attempts]
    known_costs = [c for c in costs if isinstance(c, (int, float))]
    by_kind: dict[str, dict] = {}
    for attempt in attempts:
        bucket = by_kind.setdefault(attempt.kind, {"n": 0, "intent": 0})
        bucket["n"] += 1
        bucket["intent"] += attempt.intent_hit
    return {
        "method": attempts[0].method,
        "cases": n,
        "solvable": sum(a.solvable for a in attempts),
        "solvable_rate": sum(a.solvable for a in attempts) / n,
        "intent_hits": sum(a.intent_hit for a in attempts),
        "intent_rate": sum(a.intent_hit for a in attempts) / n,
        "layout_mean": statistics.mean(a.layout for a in attempts),
        "seconds_mean": statistics.mean(a.seconds for a in attempts),
        "seconds_total": sum(a.seconds for a in attempts),
        "cost_usd_total": sum(known_costs) if len(known_costs) == n else None,
        "cost_usd_mean": (sum(known_costs) / n) if len(known_costs) == n else None,
        "errors": sum(1 for a in attempts if a.error),
        "by_kind": {
            k: {**v, "rate": v["intent"] / v["n"]} for k, v in sorted(by_kind.items())
        },
    }


def write_attempts(attempts: list[Attempt], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for attempt in attempts:
            handle.write(json.dumps(attempt.to_json()) + "\n")
    return path


def read_attempts(path: str | Path) -> list[Attempt]:
    return [
        Attempt.from_json(json.loads(line))
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


def comparison_table(summaries: list[dict]) -> str:
    """The headline table: one row per method."""
    header = (
        f"{'method':<22} {'cases':>5} {'solvable':>9} {'intent':>15} "
        f"{'layout':>7} {'s/case':>7} {'$/case':>9}"
    )
    lines = [header, "-" * len(header)]
    for s in summaries:
        cost = "n/a" if s["cost_usd_mean"] is None else f"${s['cost_usd_mean']:.4f}"
        if s["cost_usd_mean"] == 0:
            cost = "$0"
        lines.append(
            f"{s['method']:<22} {s['cases']:>5} "
            f"{s['solvable']:>4}/{s['cases']:<4} "
            f"{s['intent_hits']:>4}/{s['cases']:<4} "
            f"({100 * s['intent_rate']:>4.1f}%) "
            f"{s['layout_mean']:>7.3f} {s['seconds_mean']:>7.2f} {cost:>9}"
        )
    return "\n".join(lines)
