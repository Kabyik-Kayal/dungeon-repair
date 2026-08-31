"""Deterministic routing: the cases the verified set already decides.

No credentials and no model. The router reads the candidate set, so its whole
contract is testable against the shipped evaluation cases.
"""

import json
from pathlib import Path

from dungeon_repair.agent import run as run_agent
from dungeon_repair.agent.tools import Toolbox
from dungeon_repair.candidates import CandidateSet, verified_candidates
from dungeon_repair.edits import ADD_DOOR, Edit, UNLOCK
from dungeon_repair.route import FORCED_UNLOCK, forced, narrowed, touches_keys

CACHE = Path(__file__).resolve().parents[1] / "eval" / "candidates"
_memo: dict = {}


def _cands(case):
    """Cached enumeration. Deterministic, so the cache changes no outcome."""
    if case.id in _memo:
        return _memo[case.id]
    path = CACHE / (case.id.replace("#", "_") + ".json")
    if path.exists():
        data = json.loads(path.read_text())
        found = CandidateSet(
            level=case.broken,
            verified=[Edit.from_json(e) for e in data["verified"]],
            considered=data["considered"],
            seconds=data["seconds"],
        )
    else:
        found = verified_candidates(case.broken)
    _memo[case.id] = found
    return found


def test_a_sole_unlock_with_a_live_key_economy_is_forced(cases):
    """The rule fires only when both halves of its premise hold."""
    fired = 0
    for case in cases:
        found = _cands(case)
        edit, reason = forced(found)
        if edit is None:
            continue
        fired += 1
        assert reason == FORCED_UNLOCK
        assert edit.kind == UNLOCK
        assert [e for e in found.verified if e.kind == UNLOCK] == [edit]
        assert touches_keys(found)
    assert fired > 0, "the rule must fire somewhere on the shipped case set"


def test_forced_answers_are_right_far_more_often_than_the_agent_was(cases):
    """Pinning the measured precision, so a regression in the rule is visible."""
    fired = [(c, forced(_cands(c))[0]) for c in cases]
    fired = [(c, e) for c, e in fired if e is not None]
    right = sum(1 for c, e in fired if e == c.truth)
    assert len(fired) == 23
    assert right == 21


def test_no_key_edit_verifies_means_a_dropped_corridor(cases):
    """When no key edit repairs the level, the option list is narrowed to passages."""
    for case in cases:
        found = _cands(case)
        if touches_keys(found):
            continue
        options, _ = narrowed(found)
        assert options
        assert all(e.kind == ADD_DOOR for e in options)
        assert case.kind == "severed_corridor" or case.truth.kind == ADD_DOOR


def test_the_shape_signal_is_off_by_default(cases):
    """The default arm must reproduce the shipped headline, so it says nothing."""
    case = next(c for c in cases if forced(_cands(c))[0] is not None)
    plain = Toolbox(case.broken, _cands(case)).diagnose_tool()
    assert "Note:" not in plain


def test_the_shape_signal_names_the_only_unlockable_door(cases):
    case = next(c for c in cases if forced(_cands(c))[0] is not None)
    found = _cands(case)
    told = Toolbox(case.broken, found, signal_shape=True).diagnose_tool()
    decided, _ = forced(found)
    assert "exactly one door can be unlocked" in told
    assert f"{decided.a},{decided.b}" in told.replace(" ", "")


def test_the_doors_only_conclusion_is_deliberately_withheld(cases):
    """Measured and removed: it was true and it cost accuracy. Stage 16."""
    case = next(c for c in cases if not touches_keys(_cands(c)))
    told = Toolbox(case.broken, _cands(case), signal_shape=True).diagnose_tool()
    assert "dropped corridor" not in told
    assert "Note:" not in told


def test_the_signal_never_decides_for_the_agent(cases, scripted):
    """Routing informs; it must not answer. The model is still called."""
    case = next(c for c in cases if forced(_cands(c))[0] is not None)
    found = _cands(case)
    other = next(e for e in found.verified if e.kind != UNLOCK)
    client = scripted([("", [("submit", {"kind": other.kind, "a": other.a,
                                         "b": other.b, "reason": "mine"})])])
    attempt = run_agent(case, client=client, candidates=found, route=True)
    assert client.seen, "the agent must still be consulted"
    assert attempt.edit == other, "the agent's answer must stand"
