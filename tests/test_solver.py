"""Solver semantics, including the two facts that were established by measurement."""

import pytest

from dungeon_repair.level import Level, Passage
from dungeon_repair.solver import solve


def test_key_behind_its_own_lock_is_unwinnable():
    level = Level(
        id="t", game="test",
        rooms={"0": frozenset("s"), "1": frozenset("k"), "2": frozenset("t")},
        passages=(
            Passage("0", "1", frozenset("k")), Passage("1", "0", frozenset("k")),
            Passage("1", "2", frozenset()), Passage("2", "1", frozenset()),
        ),
    )
    result = solve(level)
    assert not result.solvable
    assert "not reachable" in result.reason


def test_one_key_cannot_open_two_doors():
    # Small keys are consumed, so which door you spend on matters. This is why
    # opened doors belong in the search state.
    level = Level(
        id="t", game="test",
        rooms={
            "0": frozenset("sk"), "1": frozenset(), "2": frozenset(), "3": frozenset("t")
        },
        passages=(
            Passage("0", "1", frozenset("k")), Passage("1", "0", frozenset("k")),
            Passage("1", "3", frozenset("k")), Passage("3", "1", frozenset("k")),
            Passage("0", "2", frozenset()), Passage("2", "0", frozenset()),
        ),
    )
    assert not solve(level).solvable

    with_second_key = level.with_symbol_added("k", "2")
    assert solve(with_second_key).solvable


def test_soft_locked_doors_are_passable():
    level = Level(
        id="t", game="test",
        rooms={"0": frozenset("s"), "1": frozenset("t")},
        passages=(Passage("0", "1", frozenset("l")), Passage("1", "0", frozenset("l"))),
    )
    assert solve(level).solvable


def test_impassable_doors_block():
    level = Level(
        id="t", game="test",
        rooms={"0": frozenset("s"), "1": frozenset("t")},
        passages=(Passage("0", "1", frozenset("s")), Passage("1", "0", frozenset("s"))),
    )
    assert not solve(level).solvable


def test_route_is_a_real_walk():
    level = Level(
        id="t", game="test",
        rooms={"0": frozenset("s"), "1": frozenset(), "2": frozenset("t")},
        passages=(
            Passage("0", "1", frozenset()), Passage("1", "0", frozenset()),
            Passage("1", "2", frozenset()), Passage("2", "1", frozenset()),
        ),
    )
    result = solve(level)
    assert result.route == ["0", "1", "2"]
    adjacency = {(p.src, p.dst) for p in level.passages}
    for a, b in zip(result.route, result.route[1:]):
        assert (a, b) in adjacency


@pytest.mark.parametrize("expected", [31])
def test_shipped_corpus_regression(corpus, expected):
    """The load-bearing regression: 31 of 38 shipped dungeons verify.

    The 7 that do not are transcription errors in the corpus, not solver bugs
    -- LttP_3 encodes one small key against three required key-locked doors.
    If this number moves, the solver semantics changed.
    """
    solvable = [level.id for level in corpus if solve(level).solvable]
    assert len(solvable) == expected
    assert "LttP_3" not in solvable
