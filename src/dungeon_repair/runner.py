"""Run a method over the evaluation set and write results and traces."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from .agent import run as run_agent
from .baselines import BASELINES
from .candidates import CandidateSet, verified_candidates
from .corrupt import Case
from .edits import Edit
from .llm import Client
from .memory import DesignMemory, mine
from .metrics import Attempt, score, summarise, write_attempts
from .trace import open_trace

METHODS: dict[str, Callable[..., Attempt]] = {**BASELINES, "agent": run_agent}

#: Methods that need model credentials.
LLM_METHODS = {"single_prompt", "agent"}


def candidates_for(case: Case, cache_dir: str | Path | None) -> CandidateSet:
    """Verified repairs for a case, cached on disk.

    Enumeration is deterministic, so caching changes nothing about the result
    and takes repeat runs from seconds per case to milliseconds.
    """
    if cache_dir is None:
        return verified_candidates(case.broken)
    path = Path(cache_dir) / (case.id.replace("#", "_") + ".json")
    if path.exists():
        data = json.loads(path.read_text())
        return CandidateSet(
            level=case.broken,
            verified=[Edit.from_json(e) for e in data["verified"]],
            considered=data["considered"],
            seconds=data["seconds"],
        )
    found = verified_candidates(case.broken)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "case_id": case.id,
                "considered": found.considered,
                "seconds": round(found.seconds, 4),
                "verified": [e.to_json() for e in found.verified],
            },
            indent=2,
        )
        + "\n"
    )
    return found


def run_method(
    method: str,
    cases: Iterable[Case],
    model: str | None = None,
    trace_dir: str | Path | None = "eval/traces",
    cache_dir: str | Path | None = "eval/candidates",
    workers: int = 1,
    on_result: Callable[[Attempt], None] | None = None,
    diagnose_first: bool = False,
    route: bool = False,
    memory: bool = False,
) -> list[Attempt]:
    if method not in METHODS:
        raise SystemExit(f"unknown method {method!r}; expected one of {', '.join(METHODS)}")
    handler = METHODS[method]
    cases = list(cases)
    run_id = time.strftime("%Y%m%d-%H%M%S")

    # One design memory per held-out dungeon, mined from the originals of every
    # *other* dungeon in the set. Holding the level out is what makes this
    # evidence rather than leakage, and the cache keeps 77 cases from re-mining
    # the same 32 corpora.
    corpus = list({case.original.id: case.original for case in cases}.values())
    memories: dict[str, DesignMemory] = {}

    def memory_for(case: Case) -> DesignMemory:
        if case.source_level not in memories:
            memories[case.source_level] = mine(corpus, exclude=case.source_level)
        return memories[case.source_level]

    def one(case: Case) -> Attempt:
        kwargs: dict = {}
        trace = None
        if method in LLM_METHODS:
            kwargs["client"] = Client(model)
            if trace_dir:
                trace = open_trace(trace_dir, run_id, case.id, method)
                kwargs["trace"] = trace
        if method == "agent":
            kwargs["candidates"] = candidates_for(case, cache_dir)
            kwargs["diagnose_first"] = diagnose_first
            kwargs["route"] = route
            if memory:
                kwargs["memory"] = memory_for(case)
        try:
            attempt = handler(case, **kwargs)
        except Exception as exc:  # noqa: BLE001 - one bad case must not kill a run
            attempt = score(
                case, method, None, 0.0, error=f"{type(exc).__name__}: {exc}"
            )
            if trace:
                trace.finish(**attempt.to_json())
        if on_result:
            on_result(attempt)
        return attempt

    if workers > 1 and method in LLM_METHODS:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            attempts = list(pool.map(one, cases))
    else:
        attempts = [one(case) for case in cases]
    return attempts


def save(method: str, attempts: list[Attempt], results_dir: str | Path = "eval/results") -> dict:
    results_dir = Path(results_dir)
    write_attempts(attempts, results_dir / f"{method}.jsonl")
    summary = summarise(attempts)
    (results_dir / f"{method}.summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    return summary
