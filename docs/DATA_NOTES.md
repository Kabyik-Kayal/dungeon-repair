# Notes on the VGLC Zelda graphs

What the corpus actually contains, and the defects worth knowing about before
trusting it. Everything here was established by parsing and solving the data,
not by reading the paper.

## Shape

`<game>/Graph Processed/*.dot` — Graphviz DOT files, one per dungeon. Nodes are
rooms with a comma-separated content label; edges are directed passages with a
comma-separated requirement label. Directly machine-readable; no tile or pixel
parsing needed. `Original/` is reference imagery and `Processed/` is tile maps —
neither is used here.

| folder | dungeons |
|---|---|
| The Legend of Zelda | 18 |
| The Legend of Zelda - Link to the Past | 12 |
| The Legend of Zelda - Link's Awakening | 8 |

All three share an identical `zelda.json` legend (Link's Awakening's copy
differs only by a trailing newline).

**Use all three.** Boss keys (`K`) and numbered switches (`S1`–`S12`) appear
only in Link to the Past and Link's Awakening. Base Zelda has zero boss keys,
so building on it alone leaves boss-key and switch logic completely untested.

## Legend

Room contents: `s` start, `t` goal ("triforce"), `k` small key, `K` boss key,
`I` key item, `e` enemy, `p` puzzle, `b` boss, `S`/`S<n>` switch.

Passage requirements: `k` key-locked, `K` boss-key-locked, `I` key-item-locked,
`S<n>` switch-locked, `l` soft-locked, `b` bombable, `s` visible but impassable.

Note that `s` means *start* on a room and *impassable* on a door, and `S` means
*switch* in both positions. Symbol meaning depends on position.

## Defects

**The legend is incomplete.** Node symbols `i` and `m`, and edge symbol `O`,
appear in the data and are not defined anywhere. They are treated as opaque
room contents and never gate a passage.

**Transcription typos.** `ep` and `ei` appear where `e,p` and `e,i` were meant
— a dropped comma. The parser splits them back out. Numeric node labels also
leak into some Link to the Past files.

**The obvious node regex is wrong.** `(\w+) [label="..."]` also matches the
target of `7 -> 8 [label="k"]`, silently overwriting room contents with edge
labels. Blank out edge statements before matching nodes.

## Seven dungeons do not verify

With correct semantics, 31 of 38 verify as winnable: Zelda 18/18, Link to the
Past 6/12, Link's Awakening 7/8.

The 7 failures are errors in the transcription, not in the solver. `LttP_3`
encodes one small key against three key-locked doors, all on the critical path,
which is unwinnable as written — the shipped game plainly is not. Run
`dungeon-repair verify -v` for the per-dungeon diagnosis.

The evaluation set is built only from the 31 that verify.

## Two semantics established by experiment

**Soft-locked doors are passable.** 101 doors carry `l` in both directions, so
it cannot mean impassable. Treating it as blocking drops verified solvability
from 31/38 to 6/38.

**Opened doors belong in the search state.** Small keys are fungible and
consumed, so which door a key is spent on changes the outcome. `(room, keys,
switches)` is under-specified and reports levels winnable that are not.

## What was ruled out

`gym-pcgrl`'s `zelda_prob.py` cannot cross-validate this solver: it is an 11×7
tile grid with one key and one door scored by Dijkstra path length — a
different representation with different mechanics and no key economy.
Reproducing 31 shipped dungeons is the stronger correctness argument.

A search of HuggingFace found no better dataset for lock-and-key dungeon
graphs. The nearest fallback, if this work ever moves to a different mechanic,
is `AlignmentResearch/boxoban-astar-solutions` (Apache 2.0), which ships A*
solutions as ready-made ground truth.
