"""Edits, corruption, and the verified candidate set."""

import random

from dungeon_repair.candidates import (
    enumerate_edits,
    first_valid,
    verified_candidates,
    verify,
)
from dungeon_repair.corrupt import build_cases, corrupt_once
from dungeon_repair.edits import ADD_DOOR, Edit, MOVE_KEY, UNLOCK
from dungeon_repair.solver import solve
from dungeon_repair.topology import layout_preservation


def test_door_edits_are_canonical():
    assert Edit(UNLOCK, "5", "3") == Edit(UNLOCK, "3", "5")
    assert Edit(ADD_DOOR, "b", "a").a == "a"
    # Room order is meaningful for a key move -- from a, to b.
    assert Edit(MOVE_KEY, "3", "5") != Edit(MOVE_KEY, "5", "3")


def test_corruption_inverse_actually_restores(corpus):
    rng = random.Random(7)
    checked = 0
    for level in corpus:
        if not solve(level).solvable:
            continue
        attempt = corrupt_once(level, rng)
        if attempt is None:
            continue
        broken, _, truth = attempt
        assert solve(truth.apply(broken)).solvable
        checked += 1
    assert checked >= 20


def test_every_case_is_genuinely_broken_and_repairable_by_its_truth(cases):
    assert len(cases) >= 50, "evaluation set should have at least 50 cases"
    for case in cases:
        assert solve(case.original).solvable, f"{case.id}: source was not winnable"
        assert not solve(case.broken).solvable, f"{case.id}: corruption did not break it"
        assert verify(case.broken, case.truth), f"{case.id}: ground truth does not repair"


def test_ground_truth_is_always_among_the_verified_candidates(cases):
    for case in cases[:12]:
        found = verified_candidates(case.broken)
        assert case.truth in found.verified, f"{case.id}: truth missing from candidates"


def test_enumeration_is_deterministic_and_least_invasive_first(cases):
    case = cases[0]
    once = [str(e) for e in enumerate_edits(case.broken)]
    twice = [str(e) for e in enumerate_edits(case.broken)]
    assert once == twice
    kinds = [e.kind for e in enumerate_edits(case.broken)]
    assert kinds == sorted(kinds, key=["unlock", "move_key", "add_key", "add_door"].index)


def test_first_valid_always_repairs_but_rarely_matches(cases):
    hits = 0
    for case in cases:
        edit, _, _ = first_valid(case.broken)
        assert edit is not None, f"{case.id}: no single-edit repair found"
        assert verify(case.broken, edit)
        hits += edit == case.truth
    # The deterministic repairer clears the solvability gate every time and
    # still misses the designer's intent on most cases. That gap is the project.
    assert hits < len(cases) * 0.5


def test_a_single_edit_preserves_almost_all_of_the_layout(cases):
    case = cases[0]
    repaired = case.truth.apply(case.broken)
    assert layout_preservation(case.original, repaired) == 1.0


def test_case_set_is_reproducible_from_the_seed(corpus):
    first = build_cases(corpus, per_kind=1, seed=99)
    second = build_cases(corpus, per_kind=1, seed=99)
    assert [(c.id, str(c.truth)) for c in first] == [(c.id, str(c.truth)) for c in second]


def test_the_hard_case_is_actually_hard(cases):
    """The authored case: many verified repairs, one that keeps the design."""
    hard = next((c for c in cases if c.id == "spiral_keep#hard"), None)
    if hard is None:
        import pytest

        pytest.skip("hard case not built; run scripts/make_hard_case.py")

    found = verified_candidates(hard.broken)
    assert len(found) > 50, "a hard case needs plenty of correct-but-wrong answers"
    assert hard.truth in found.verified

    # Ten repairs move the stranded key somewhere reachable. Only one puts it
    # back in the alcove built for it, so kind alone cannot solve this case.
    same_kind = [e for e in found.verified if e.kind == hard.truth.kind and e.a == hard.truth.a]
    assert len(same_kind) > 5

    deterministic, _, _ = first_valid(hard.broken)
    assert deterministic != hard.truth, "the deterministic pick should miss this one"
