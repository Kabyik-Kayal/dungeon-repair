"""The agent loop: tool dispatch, the verification gate, traces, checkpoints.

Driven by a scripted model stand-in, so the loop's guarantees are tested
without credentials or network.
"""

import json

from dungeon_repair.agent import run as run_agent
from dungeon_repair.agent.tools import Toolbox, ToolError
from dungeon_repair.candidates import verified_candidates
from dungeon_repair.trace import Trace, open_trace, render_markdown


def _edit_args(edit, reason="because"):
    return {"kind": edit.kind, "a": edit.a, "b": edit.b, "reason": reason}


def _guess_args(edit, reasoning="the diagnosis points here"):
    """Arguments for `hypothesise`, which now gates the option tools."""
    rooms = [r for r in (edit.a, edit.b) if r]
    return {"repair_kind": edit.kind, "rooms": rooms, "reasoning": reasoning}


def _committed(box, edit):
    """A Toolbox with the hypothesis gate already satisfied."""
    box.hypothesise(**_guess_args(edit))
    return box


def test_submit_rejects_an_unverified_repair(cases):
    case = cases[0]
    box = Toolbox(case.broken)
    bogus = next(
        e for e in box.candidates.verified if e  # any verified edit, then break it
    )
    # An "add_key" in a room that already holds one is refused on its arguments;
    # an edit that simply does not repair is refused by the verification gate.
    unverified = None
    from dungeon_repair.edits import ADD_KEY, Edit

    for room in sorted(case.broken.rooms):
        candidate = Edit(ADD_KEY, room)
        if candidate not in box.verified and "k" not in case.broken.rooms[room]:
            unverified = candidate
            break
    assert unverified is not None
    _committed(box, unverified)

    try:
        box.submit(**_edit_args(unverified))
        raise AssertionError("unverified repair was accepted")
    except ToolError as exc:
        assert "not a verified repair" in str(exc)
    assert box.submission is None

    box.submit(**_edit_args(bogus))
    assert box.submission.edit == bogus


def test_submit_requires_a_reason(cases):
    box = Toolbox(cases[0].broken)
    edit = box.candidates.verified[0]
    _committed(box, edit)
    try:
        box.submit(kind=edit.kind, a=edit.a, b=edit.b, reason="  ")
        raise AssertionError("submission without a reason was accepted")
    except ToolError as exc:
        assert "reason" in str(exc)


def test_tools_report_bad_arguments_instead_of_raising_upward(cases):
    box = Toolbox(cases[0].broken)
    _committed(box, box.candidates.verified[0])
    for name, args in [
        ("repair_options", {"kind": "teleport"}),
        ("repair_options", {"involving_room": "nowhere"}),
        ("room_detail", {"rooms": ["nowhere"]}),
        ("compare", {"options": []}),
    ]:
        try:
            box.call(name, args)
            raise AssertionError(f"{name}{args} should have been rejected")
        except ToolError:
            pass


def test_compare_flags_a_repair_that_does_not_work(cases):
    case = cases[0]
    box = Toolbox(case.broken)
    from dungeon_repair.edits import ADD_KEY, Edit

    broken_choice = next(
        Edit(ADD_KEY, room)
        for room in sorted(case.broken.rooms)
        if Edit(ADD_KEY, room) not in box.verified and "k" not in case.broken.rooms[room]
    )
    _committed(box, broken_choice)
    text = box.compare([{"kind": broken_choice.kind, "a": broken_choice.a}])
    assert "does not make the dungeon winnable" in text


def test_agent_picks_the_truth_when_the_model_asks_for_it(cases, scripted, tmp_path):
    case = cases[0]
    client = scripted([
        ("Let me look at the failure.", [("diagnose", {})]),
        ("Committing to a read.", [("hypothesise", _guess_args(case.truth))]),
        ("Now the options.", [("repair_options", {"kind": case.truth.kind, "limit": 5})]),
        ("Submitting.", [("submit", _edit_args(case.truth, "restores the cut corridor"))]),
    ])
    trace = open_trace(tmp_path, "test", case.id, "agent")
    attempt = run_agent(case, client=client, trace=trace,
                        candidates=verified_candidates(case.broken))

    assert attempt.intent_hit and attempt.solvable
    assert attempt.rationale
    assert attempt.usage["calls"] == 4
    assert attempt.extra["hypothesis"]["repair_kind"] == case.truth.kind

    kinds = [json.loads(line)["kind"] for line in trace.path.read_text().splitlines()]
    assert kinds[0] == "instructions"
    assert "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-2:] == ["human_checkpoint", "finish"]
    assert "## t=" in render_markdown(trace.path)


def test_agent_retries_after_a_rejected_submission(cases, scripted):
    case = cases[0]
    from dungeon_repair.edits import ADD_KEY, Edit

    box = Toolbox(case.broken)
    unverified = next(
        Edit(ADD_KEY, room)
        for room in sorted(case.broken.rooms)
        if Edit(ADD_KEY, room) not in box.verified and "k" not in case.broken.rooms[room]
    )
    client = scripted([
        ("A read first.", [("hypothesise", _guess_args(case.truth))]),
        ("Trying this.", [("submit", _edit_args(unverified))]),
        ("Then this one.", [("submit", _edit_args(case.truth, "second attempt"))]),
    ])
    attempt = run_agent(case, client=client, candidates=box.candidates)
    assert attempt.intent_hit
    assert attempt.extra["steps"] == 3


def test_agent_never_ships_an_unplayable_level(cases, scripted):
    """Even a model that only ever proposes broken repairs cannot break the level."""
    case = cases[0]
    from dungeon_repair.edits import ADD_KEY, Edit

    box = Toolbox(case.broken)
    unverified = next(
        Edit(ADD_KEY, room)
        for room in sorted(case.broken.rooms)
        if Edit(ADD_KEY, room) not in box.verified and "k" not in case.broken.rooms[room]
    )
    client = scripted(
        [("a read", [("hypothesise", _guess_args(unverified))])]
        + [("nope", [("submit", _edit_args(unverified))])] * 6
    )
    attempt = run_agent(case, client=client, candidates=box.candidates, max_steps=4)
    assert attempt.edit is None
    assert attempt.error


def test_human_checkpoint_can_refuse(cases, scripted):
    case = cases[0]
    client = scripted([
        ("a read", [("hypothesise", _guess_args(case.truth))]),
        ("here", [("submit", _edit_args(case.truth, "reason"))]),
    ])
    attempt = run_agent(
        case, client=client, candidates=verified_candidates(case.broken),
        approve=lambda question: False,
    )
    assert attempt.edit is None
    assert "declined" in attempt.error


def test_option_tools_are_gated_behind_a_hypothesis(cases):
    """The agent must commit to a read of the bug before it may browse repairs.

    This is the whole point of the two-phase flow: an agent that sees the menu
    first can pick from it instead of reasoning toward it.
    """
    box = Toolbox(cases[0].broken, require_hypothesis=True)
    for name, args in [
        ("repair_options", {}),
        ("compare", {"options": [{"kind": "unlock", "a": "0", "b": "1"}]}),
        ("submit", {"kind": "unlock", "a": "0", "b": "1", "reason": "x"}),
    ]:
        try:
            box.call(name, args)
            raise AssertionError(f"{name} answered before a hypothesis was made")
        except ToolError as exc:
            assert "hypothesise" in str(exc)

    # diagnose and room_detail stay open -- they are how you form the view.
    assert box.call("diagnose", {})
    assert box.call("room_detail", {"rooms": [sorted(cases[0].broken.rooms)[0]]})


def test_first_hypothesis_is_locked_for_scoring(cases):
    """Revision is allowed; the score reflects the pre-menu commitment."""
    case = cases[0]
    box = Toolbox(case.broken, require_hypothesis=True)
    box.hypothesise(repair_kind="add_key", rooms=[], reasoning="first read")
    box.hypothesise(repair_kind="unlock", rooms=[], reasoning="changed my mind")
    assert box.first_hypothesis.repair_kind == "add_key"
    assert box.hypothesis.repair_kind == "unlock"


def test_hypothesis_gate_is_off_by_default(cases):
    """The shipped agent does not gate; the gate is an opt-in experiment arm."""
    box = Toolbox(cases[0].broken)
    assert box.repair_options(limit=3)
    assert box.first_hypothesis is None
