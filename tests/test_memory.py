"""Design memory: motifs mined from the designer's other dungeons.

The contract that matters is the hold-out. Everything the agent reads about
habits must come from dungeons other than the one it is repairing, or the
measurement is worthless.
"""

import pytest

from dungeon_repair.agent.tools import Toolbox, ToolError
from dungeon_repair.edits import MOVE_KEY
from dungeon_repair.level import ENEMY, SMALL_KEY
from dungeon_repair.memory import DesignMemory, mine


def _corpus(cases):
    return list({c.original.id: c.original for c in cases}.values())


def test_the_repaired_dungeon_is_held_out(cases):
    corpus = _corpus(cases)
    held = corpus[0].id
    memory = mine(corpus, exclude=held)
    assert memory.dungeons == len(corpus) - 1
    # identical to mining a corpus that never contained it
    without = mine([lv for lv in corpus if lv.id != held])
    assert [m.line() for m in memory.motifs] == [m.line() for m in without.motifs]


def test_motifs_carry_the_numbers_that_justify_them(cases):
    memory = mine(_corpus(cases))
    enemy = memory.by_name("holds an enemy")
    assert enemy is not None
    # measured on this corpus: keys sit with enemies far more often than chance
    assert enemy.lift > 1.3
    assert 0 < enemy.rate <= 1 and 0 < enemy.base <= 1
    assert "lift" in memory.summary()
    assert "filters, not as a ranking" in memory.summary()


def test_an_empty_memory_says_so_rather_than_inventing(cases):
    memory = mine([], exclude="")
    assert memory.dungeons == 0
    assert "No other dungeons" in memory.summary()


def test_annotation_only_fires_on_motifs_the_room_actually_has(cases):
    case = cases[0]
    memory = mine(_corpus(cases), exclude=case.source_level)
    for room, contents in case.broken.rooms.items():
        note = memory.annotate(case.broken, room)
        if ENEMY not in contents:
            assert "holds an enemy" not in note


def test_design_rhythm_is_absent_unless_a_memory_is_loaded(cases):
    case = cases[0]
    plain = Toolbox(case.broken)
    assert not any(t["function"]["name"] == "design_rhythm" for t in plain.schemas())
    with pytest.raises(ToolError):
        plain.design_rhythm()

    memory = mine(_corpus(cases), exclude=case.source_level)
    box = Toolbox(case.broken, memory=memory)
    assert any(t["function"]["name"] == "design_rhythm" for t in box.schemas())
    assert "lift" in box.design_rhythm()


def test_only_key_moves_are_annotated_with_habits(cases):
    """Attaching key motifs to a door edit would dress noise up as evidence."""
    case = next(c for c in cases if c.kind == "displaced_key")
    memory = mine(_corpus(cases), exclude=case.source_level)
    box = Toolbox(case.broken, memory=memory)
    for edit in box.candidates.verified:
        note = box._rhythm(edit)
        if edit.kind != MOVE_KEY:
            assert note == ""


def test_the_memory_is_withheld_where_no_key_edit_is_legal(cases):
    """A tool that cannot apply is not neutral -- it costs steps and accuracy."""
    from dungeon_repair.route import touches_keys

    doors_only = [c for c in cases if not touches_keys(Toolbox(c.broken).candidates)]
    assert doors_only, "the shipped set must contain doors-only cases"
    case = doors_only[0]
    memory = mine(_corpus(cases), exclude=case.source_level)
    box = Toolbox(case.broken, memory=memory)
    assert not box.rhythm_available
    assert not any(t["function"]["name"] == "design_rhythm" for t in box.schemas())
    with pytest.raises(ToolError):
        box.design_rhythm()
