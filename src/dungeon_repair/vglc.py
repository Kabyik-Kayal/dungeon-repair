"""Parse VGLC Zelda room graphs into :class:`~dungeon_repair.level.Level`.

The corpus ships each dungeon as a Graphviz DOT file under
``<game>/Graph Processed/*.dot``. Nodes are rooms, edges are passages, and both
carry a comma-separated label of legend symbols.

Two things in this data bite:

1. A naive node regex also matches the *target* of an edge statement, because
   ``7 -> 8 [label=""]`` ends in the same ``<id> [label="..."]`` shape. Every
   room label then gets silently overwritten by an edge label. Edge statements
   are blanked out before nodes are matched.
2. A handful of labels are transcription typos -- ``ep`` and ``ei`` are
   ``e,p`` and ``e,i`` with the comma dropped. They are split back out.
"""

from __future__ import annotations

import re
from pathlib import Path

from .level import Level, Passage

#: The three Zelda folders in the corpus. They share one legend file.
GAMES: dict[str, str] = {
    "LoZ": "The Legend of Zelda",
    "LttP": "The Legend of Zelda - Link to the Past",
    "LA": "The Legend of Zelda - Link's Awakening",
}

_EDGE = re.compile(r'(\w+)\s*->\s*(\w+)\s*\[label="([^"]*)"\]')
_NODE = re.compile(r'\b(\w+)\s*\[label="([^"]*)"\]')

#: Concatenated symbols the corpus writes without their separating comma.
_TYPO_SPLITS = {"ep": ("e", "p"), "ei": ("e", "i")}


def _symbols(label: str) -> frozenset[str]:
    out: set[str] = set()
    for raw in label.replace("\n", "").split(","):
        token = raw.strip()
        if not token:
            continue
        out.update(_TYPO_SPLITS.get(token, (token,)))
    return frozenset(out)


def parse_dot(path: str | Path, game: str = "") -> Level:
    """Read one ``.dot`` dungeon graph."""
    path = Path(path)
    text = path.read_text()

    passages = [
        Passage(m.group(1), m.group(2), _symbols(m.group(3)))
        for m in _EDGE.finditer(text)
    ]

    # Blank out edge statements (preserving offsets) so the node pattern cannot
    # match an edge target. Without this every room label is wrong.
    without_edges = _EDGE.sub(lambda m: " " * (m.end() - m.start()), text)
    rooms = {
        m.group(1): _symbols(m.group(2)) for m in _NODE.finditer(without_edges)
    }

    # A passage may name a room that has no node statement of its own.
    for p in passages:
        rooms.setdefault(p.src, frozenset())
        rooms.setdefault(p.dst, frozenset())

    return Level(
        id=path.stem,
        game=game or path.parent.parent.name,
        rooms=rooms,
        passages=tuple(passages),
    )


def graph_dir(root: str | Path, game_key: str) -> Path:
    return Path(root) / GAMES[game_key] / "Graph Processed"


def dot_files(root: str | Path, game_key: str) -> list[Path]:
    return sorted(graph_dir(root, game_key).glob("*.dot"))


def load_corpus(root: str | Path) -> list[Level]:
    """Every Zelda dungeon in the corpus, across all three games."""
    levels: list[Level] = []
    for key in GAMES:
        for path in dot_files(root, key):
            levels.append(parse_dot(path, game=key))
    return levels
