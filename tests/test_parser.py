"""The DOT parser, and the trap that silently corrupts every room label."""

from dungeon_repair.level import SMALL_KEY, START
from dungeon_repair.vglc import parse_dot


def test_edge_targets_do_not_overwrite_room_labels(tmp_path):
    # `7 -> 8 [label="k"]` ends in the same shape as a node statement. A naive
    # node regex matches the edge target and rewrites room 8's contents.
    dot = tmp_path / "trap.dot"
    dot.write_text(
        'digraph {\n'
        '0 [label="s"]\n'
        '8 [label="t"]\n'
        '0 -> 8 [label="k"]\n'
        '8 -> 0 [label="k"]\n'
        '}\n'
    )
    level = parse_dot(dot, game="test")
    assert level.rooms["8"] == frozenset({"t"})
    assert level.rooms["0"] == frozenset({"s"})
    assert {p.requires for p in level.passages} == {frozenset({"k"})}


def test_missing_comma_typos_are_split(tmp_path):
    dot = tmp_path / "typo.dot"
    dot.write_text('digraph {\n1 [label="ep"]\n2 [label="ei"]\n}\n')
    level = parse_dot(dot, game="test")
    assert level.rooms["1"] == frozenset({"e", "p"})
    assert level.rooms["2"] == frozenset({"e", "i"})


def test_corpus_shape(corpus):
    assert len(corpus) == 38
    per_game = {}
    for level in corpus:
        per_game[level.game] = per_game.get(level.game, 0) + 1
    assert per_game == {"LoZ": 18, "LttP": 12, "LA": 8}
    for level in corpus:
        assert level.start is not None, f"{level.id} has no start"
        assert level.goals, f"{level.id} has no goal"


def test_boss_keys_and_switches_only_exist_outside_base_zelda(corpus):
    # Justifies using all three folders: base Zelda alone leaves the boss-key
    # and switch logic untested.
    from dungeon_repair.level import BOSS_KEY

    boss_key_games = {
        level.game for level in corpus if level.rooms_with(BOSS_KEY)
    }
    assert boss_key_games == {"LttP", "LA"}
