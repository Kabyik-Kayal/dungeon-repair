"""Command line entry point.

    dungeon-repair verify                 solver over the shipped corpus
    dungeon-repair build-cases            seeded corruption -> evaluation set
    dungeon-repair run METHOD             a method over the evaluation set
    dungeon-repair compare                the headline comparison table
    dungeon-repair repair CASE            one case, interactively, with approval
    dungeon-repair check-model            one cheap call to check the setup
    dungeon-repair trace PATH             render a trajectory as markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .candidates import first_valid, verified_candidates
from .corrupt import build_cases, read_cases, write_cases
from .llm import load_dotenv
from .metrics import comparison_table, read_attempts, summarise
from .runner import METHODS, candidates_for, run_method, save
from .solver import solve
from .trace import render_markdown
from .vglc import GAMES, load_corpus

DATA = "data/TheVGLC"
CASES = "eval/cases"
RESULTS = "eval/results"


def cmd_verify(args: argparse.Namespace) -> int:
    levels = load_corpus(args.data)
    if args.game:
        levels = [lv for lv in levels if lv.game == args.game]
    per_game: dict[str, list[int]] = {}
    for level in levels:
        result = solve(level)
        bucket = per_game.setdefault(level.game, [0, 0])
        bucket[0] += result.solvable
        bucket[1] += 1
        if args.verbose or not result.solvable:
            status = "solvable  " if result.solvable else "UNSOLVABLE"
            detail = "" if result.solvable else f"  {result.reason}"
            print(f"  {level.game:<5} {level.id:<12} {len(level.rooms):>3} rooms  "
                  f"{status}{detail}")
    total_ok = sum(v[0] for v in per_game.values())
    total = sum(v[1] for v in per_game.values())
    print()
    for game, (ok, n) in per_game.items():
        print(f"  {game:<5} {ok}/{n}")
    print(f"  TOTAL {total_ok}/{total} shipped dungeons verify as winnable")
    return 0


def cmd_build_cases(args: argparse.Namespace) -> int:
    levels = load_corpus(args.data)
    cases = build_cases(levels, per_kind=args.per_kind, seed=args.seed)
    write_cases(cases, args.out)
    kinds: dict[str, int] = {}
    for case in cases:
        kinds[case.kind] = kinds.get(case.kind, 0) + 1
    print(f"wrote {len(cases)} cases to {args.out}")
    for kind, count in sorted(kinds.items()):
        print(f"  {kind:<18} {count}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    load_dotenv()
    cases = read_cases(args.cases)
    if args.kind:
        cases = [c for c in cases if c.kind == args.kind]
    if args.case:
        cases = [c for c in cases if c.id in args.case]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        print("no cases matched", file=sys.stderr)
        return 1

    print(f"{args.method}: {len(cases)} case(s)")
    done = [0]

    def progress(attempt) -> None:
        done[0] += 1
        mark = "HIT " if attempt.intent_hit else ("ok  " if attempt.solvable else "FAIL")
        note = f"  {attempt.error}" if attempt.error else ""
        print(f"  [{done[0]:>3}/{len(cases)}] {attempt.case_id:<14} {attempt.kind:<17} "
              f"{mark} {str(attempt.edit or '-'):<26} {attempt.seconds:>6.2f}s{note}")

    attempts = run_method(
        args.method,
        cases,
        model=args.model,
        trace_dir=args.traces,
        cache_dir=args.cache,
        workers=args.workers,
        on_result=progress,
        diagnose_first=getattr(args, "diagnose_first", False),
        route=getattr(args, "route", False),
        memory=getattr(args, "memory", False),
    )
    summary = save(args.method, attempts, args.results)
    print()
    print(comparison_table([summary]))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    summaries = []
    order = ["rejection", "single_prompt", "first_valid", "agent"]
    for method in order:
        path = Path(args.results) / f"{method}.jsonl"
        if path.exists():
            summaries.append(summarise(read_attempts(path)))
    if not summaries:
        print(f"no results in {args.results}; run some methods first", file=sys.stderr)
        return 1
    print(comparison_table(summaries))
    print()
    print("intent recovery by corruption kind")
    kinds = sorted({k for s in summaries for k in s["by_kind"]})
    header = f"  {'kind':<18}" + "".join(f"{s['method']:>16}" for s in summaries)
    print(header)
    for kind in kinds:
        row = f"  {kind:<18}"
        for summary in summaries:
            bucket = summary["by_kind"].get(kind)
            cell = f"{bucket['intent']}/{bucket['n']}" if bucket else "-"
            row += f"{cell:>16}"
        print(row)
    return 0


def cmd_repair(args: argparse.Namespace) -> int:
    load_dotenv()
    cases = {c.id: c for c in read_cases(args.cases)}
    case = cases.get(args.case)
    if case is None:
        print(f"no such case: {args.case}. Available: {', '.join(sorted(cases)[:8])} ...",
              file=sys.stderr)
        return 1

    print(case.broken.outline())
    print()
    diagnosis = solve(case.broken)
    print(f"solver: {diagnosis.summary()}")
    found = candidates_for(case, args.cache)
    print(f"verified repairs available: {len(found)} "
          f"({', '.join(f'{k}={v}' for k, v in found.counts().items() if v)})")
    deterministic, considered, _ = first_valid(case.broken)
    print(f"deterministic first-valid pick: {deterministic}")
    print()

    def approve(question: str) -> bool:
        print(question)
        answer = input("apply? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    from .agent import run as run_agent
    from .llm import Client
    from .trace import open_trace

    trace = open_trace(args.traces, "interactive", case.id, "agent") if args.traces else None
    attempt = run_agent(
        case,
        client=Client(args.model),
        trace=trace,
        candidates=found,
        approve=None if args.yes else approve,
    )
    print()
    print(f"agent chose: {attempt.edit}")
    print(f"reason: {attempt.rationale}")
    print(f"designer's actual edit: {case.truth}  "
          f"-> {'MATCH' if attempt.intent_hit else 'different'}")
    print(f"still winnable: {attempt.solvable}; layout preserved: {attempt.layout:.3f}")
    if attempt.error:
        print(f"error: {attempt.error}")
    if trace:
        print(f"trace: {trace.path}")
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    cases = {c.id: c for c in read_cases(args.cases)}
    case = cases.get(args.case)
    if case is None:
        print(f"no such case: {args.case}", file=sys.stderr)
        return 1
    found = verified_candidates(case.broken)
    print(f"{case.id}: {len(found)} verified repairs out of {found.considered} "
          f"candidates in {found.seconds:.2f}s")
    for kind, edits in found.by_kind().items():
        if edits:
            print(f"  {kind:<10} {len(edits):>4}: "
                  f"{', '.join(str(e) for e in edits[:6])}"
                  f"{' ...' if len(edits) > 6 else ''}")
    print(f"  ground truth: {case.truth}")
    return 0


def cmd_check_model(args: argparse.Namespace) -> int:
    """One cheap call that proves credentials, model string, and tool calling.

    Worth running before committing to a full evaluation: the two model-backed
    methods are the only steps that cost anything, and a wrong model string or
    a model without tool calling fails 77 times instead of once.
    """
    load_dotenv()
    from .llm import Client, MissingCredentials, price_of, resolve_model

    model = resolve_model(args.model)
    rate = price_of(model)
    print(f"model:     {model}")
    if rate:
        print(f"base rate: ${rate[0]:.2f} in / ${rate[1]:.2f} out per 1M tokens")
    else:
        print("base rate: unknown to litellm -- cost will be reported as n/a. "
              "Add an entry to PRICE_OVERRIDES in llm.py to fix that.")

    probe = [{
        "type": "function",
        "function": {
            "name": "report_ready",
            "description": "Report that tool calling works.",
            "parameters": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
        },
    }]
    client = Client(args.model, max_tokens=256)
    try:
        reply = client.complete(
            [{"role": "user", "content": "Call report_ready with ok set to true."}],
            tools=probe,
        )
    except MissingCredentials as exc:
        print(f"\ncredentials: MISSING\n  {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - the whole point is to surface it
        print(f"\ncall failed: {type(exc).__name__}: {exc}")
        return 1

    called = [c["name"] for c in reply.tool_calls]
    usage = client.usage.to_json()
    cost = usage["cost_usd"]
    print("\ncredentials:  ok")
    print(f"tool calling: {'ok -> ' + ', '.join(called) if called else 'NO TOOL CALL RETURNED'}")
    print(f"tokens:       {usage['input_tokens']} in / {usage['output_tokens']} out")
    print(f"cost:         {'n/a' if cost is None else f'${cost:.6f}'}")
    if not called:
        print("\nThe agent needs tool calling. Pick a model that supports it.")
        return 1
    print("\nReady. Next: dungeon-repair run agent --limit 5")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    text = render_markdown(args.path)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dungeon-repair", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("verify", help="run the solver over the shipped corpus")
    p.add_argument("--data", default=DATA)
    p.add_argument("--game", choices=sorted(GAMES))
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("build-cases", help="generate the seeded evaluation set")
    p.add_argument("--data", default=DATA)
    p.add_argument("--out", default=CASES)
    p.add_argument("--per-kind", type=int, default=1)
    p.add_argument("--seed", type=int, default=1234)
    p.set_defaults(func=cmd_build_cases)

    p = sub.add_parser("run", help="run one method over the evaluation set")
    p.add_argument("method", choices=sorted(METHODS))
    p.add_argument("--cases", default=CASES)
    p.add_argument("--results", default=RESULTS)
    p.add_argument("--traces", default="eval/traces")
    p.add_argument("--cache", default="eval/candidates")
    p.add_argument("--model", default=None)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--kind", default=None)
    p.add_argument("--case", action="append", default=None)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument(
        "--diagnose-first",
        action="store_true",
        help="agent must commit to a hypothesis before it may browse repairs",
    )
    p.add_argument(
        "--route",
        action="store_true",
        help="tell the agent what the shape of the verified set already rules out",
    )
    p.add_argument(
        "--memory",
        action="store_true",
        help="give the agent design motifs mined from the designer's other dungeons",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("compare", help="print the comparison table")
    p.add_argument("--results", default=RESULTS)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("repair", help="repair one case interactively")
    p.add_argument("case")
    p.add_argument("--cases", default=CASES)
    p.add_argument("--cache", default="eval/candidates")
    p.add_argument("--traces", default="eval/traces")
    p.add_argument("--model", default=None)
    p.add_argument("--yes", action="store_true", help="skip the approval prompt")
    p.set_defaults(func=cmd_repair)

    p = sub.add_parser("candidates", help="show every verified repair for a case")
    p.add_argument("case")
    p.add_argument("--cases", default=CASES)
    p.set_defaults(func=cmd_candidates)

    p = sub.add_parser("check-model", help="verify credentials, model, tool calling")
    p.add_argument("--model", default=None)
    p.set_defaults(func=cmd_check_model)

    p = sub.add_parser("trace", help="render a trajectory as markdown")
    p.add_argument("path")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_trace)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
