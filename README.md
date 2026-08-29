# Dungeon Repair

Verify that a procedurally generated lock-and-key dungeon can actually be
finished, and when it cannot, repair it the way its designer would have.

```bash
dungeon-repair verify          # 31 of 38 shipped Zelda dungeons verify as winnable
dungeon-repair repair 'LA_3#2'   # diagnose one broken dungeon and fix it, with approval
dungeon-repair compare         # baselines against the agent, on the same 77 cases
```

## Who this is for

Solo and small-team developers who generate levels procedurally and ship them
without a human walking every seed. Dungeon crawlers, roguelikes, metroidvanias
— anything where progress is gated by keys, switches, and locked doors.

## The bottleneck

A generated dungeon can be structurally fine and still unwinnable. The key for
a door generates behind that door. A corridor gets dropped and a wing is
orphaned. Three locked doors sit on the critical path and the generator only
placed two keys.

A flood fill does not catch this. Once keys are consumed and switches change
world state, whether a room is reachable depends on what the player is carrying
and what they have already spent — it is a search over player state, not plain
connectivity. So teams do one of two things: playtest every seed by hand, which
does not scale, or reject and reroll until a level passes, which throws away
the hand-tuned layout and teaches you nothing about what was wrong.

That is the problem this started on. Measuring it changed the answer.

## What measurement changed

The plan was for an agent to diagnose the failure, propose a fix, verify it,
and retry. Before building that, the assumption was tested: enumerate every
single edit in a small vocabulary — move a key, add a key, unlock a door, add a
corridor — and ask a solver about each one.

**It repairs every broken level tested, deterministically, in under a second,
for no API spend.** Making a level winnable is not an agentic problem, and an
LLM put up against that loses on every axis at once.

The same experiment showed where the difficulty actually is:

- There is a **median of 60 provably-correct single-edit repairs per broken
  level** (min 6, max 612).
- Ranked least-invasive first, the deterministic repairer clears the
  solvability gate on **77 of 77** cases and recovers the designer's actual
  intent on **26 of 77**. It repairs a severed corridor by connecting two rooms
  on opposite sides of the dungeon. The level passes the check and is still
  unshippable.

Correctness is free. Judgment is scarce. So the architecture inverted:

> The solver is the oracle. Enumeration is the candidate generator. **The agent
> never has to make the level winnable — it chooses among repairs that are
> already proven correct, and explains the choice.**

The agent cannot ship an unplayable level, because `submit` refuses any edit
the solver has not verified. It spends its entire budget on the one question
the solver cannot answer.

## How it works

```
VGLC .dot graphs ──► parser ──► Level ──► solver ──► winnable? + diagnosis
                                  │                        │
                     seeded corruption            candidate generator
                                  │                        │
                        broken level + known truth   ~60 verified repairs
                                        │                  │
                                        └──────► agent ◄───┘
                                        tools: diagnose, repair_options,
                                        compare, room_detail, submit
                                                   │
                                        human checkpoint ──► repaired level
```

- **Solver** (`solver.py`) — breadth-first search over `(room, keys collected,
  doors opened, item/boss-key/switch flags)`. Returns a winning route or proof
  that no ordering of key spends reaches the goal.
- **Candidate generator** (`candidates.py`) — enumerates the edit vocabulary and
  keeps what the solver certifies.
- **Agent** (`agent/`) — gets the diagnosis and the verified set, and picks. Its
  tools answer design questions, not correctness ones: how far apart are these
  rooms, what does this do to the key economy, does this repair collapse the
  winning route.
- **Human checkpoint** — nothing is applied without approval. Evaluation runs
  auto-approve and the trace records that it was automatic.

## The data

[The Video Game Level Corpus](https://github.com/TheVGLC/TheVGLC) (MIT), room
graphs transcribed from three shipped Zelda games: 18 + 12 + 8 = 38 dungeons.
All three are used, not one — boss keys and numbered switches appear **only**
in Link to the Past and Link's Awakening, so building on base Zelda alone
leaves that logic untested.

31 of the 38 verify as winnable. The other 7 are transcription errors in the
corpus, not solver bugs: `LttP_3` encodes one small key against three
key-locked doors, all on the critical path. The evaluation set is built from
the 31 that verify. Surfacing real errors in a published research dataset is a
side effect of having a solver worth trusting; see [docs/DATA_NOTES.md](docs/DATA_NOTES.md).

## The evaluation

77 cases: the 31 verified dungeons, each mutated by a fixed-seed script, plus
one hand-authored hard case. Three mutations, each a single change a generator
plausibly makes:

| kind | what breaks | ground-truth repair |
|---|---|---|
| `displaced_key` | a small key generates in the wrong room | move it back |
| `severed_corridor` | a passage is dropped | reopen it |
| `spurious_lock` | a door that should be open is key-locked | unlock it |

A mutation is only kept if the solver confirms it genuinely broke the level, so
every case sits on the critical path. Because the mutation is seeded, the
designer's intended repair is known, which makes intent recovery objective
rather than a matter of taste.

**The hard case** (`spiral_keep#hard`) is authored, not sampled. The keep
repeats one rhythm three times — an alcove holding the key for the gate
directly ahead — and the third key generates behind its own gate. 115 repairs
verify. Ten of them move the stranded key. One puts it back in its alcove.

### Metrics

- **Intent recovery** (primary) — did the chosen repair match the edit that
  broke the level.
- **Solvability** — a gate, not an achievement. Every method with solver access
  clears it by construction; it is reported so the comparison stays legible.
- **Layout preservation** — Jaccard similarity of doors-with-locks and
  room-contents against the original.
- **Wall time and cost per case.**

### Results

77 cases. `dungeon-repair compare` regenerates this table from
[`eval/results/`](eval/results).

| method | solvable | intent recovery | layout | s/case | $/case |
|---|---|---|---|---|---|
| rejection sampling | 77/77 | 0/77 (0.0%) | 0.034 | 0.00 | $0 |
| single prompt, no tools | 61/77 | 23/77 (29.9%) | 0.961 | 29.9 | $0.0035 |
| enumerate, first valid | 77/77 | 26/77 (33.8%) | 0.965 | 0.06 | $0 |
| **agent** | **77/77** | **34/77 (44.2%)** | **0.966** | 27.4 | $0.0051 |

**The agent recovers designer intent on 44.2% of cases against 33.8% for the
best baseline** — eight more cases, a 31% relative improvement — while never
shipping an unplayable level. Run with `openai/gpt-5.6-luna`; the full 77-case
run costs about $0.39 for the agent and $0.27 for the single-prompt baseline.

The single-prompt baseline is the one to look at twice. It has no solver, so it
is the only method here that ships broken levels: **16 of its 77 "repairs"
leave the dungeon unwinnable.** It is not merely worse than the agent, it is
unsafe in a way the number 29.9% hides.

Intent recovery by corruption kind:

| kind | rejection | single prompt | first valid | agent |
|---|---|---|---|---|
| `displaced_key` | 0/15 | 1/15 | 0/15 | **1/15** |
| `severed_corridor` | 0/31 | 5/31 | 1/31 | **9/31** |
| `spurious_lock` | 0/31 | 17/31 | 25/31 | **24/31** |

That breakdown is the whole argument, and it is not flattering. Least-invasive-
first ordering makes the deterministic repairer strong on spurious locks —
unlocking a door is the first thing it tries, and often the right one — and the
agent barely improves on it there, 26 against 25. The agent's entire advantage
comes from severed corridors, where it goes from 1 to 8 by reasoning about
which rooms plausibly sat next to each other.

**On displaced keys it scores 1 of 15.** That is the honest headline, and the
failure is more specific than the number: the agent mostly does not pick a
wrong room to put the key back in — it does not choose to move the key at all.

We ran two experiments to fix that, and both failed informatively.

**Rebalancing the tools** (Stage 13). The option list led with `unlock` and
truncated, so on many cases the agent never saw the alternatives. Fixing it
moved unlock choices from 48 to 40 and the score by **exactly nothing** —
34/77 either way, four gains and four losses.

**Forcing a diagnosis first** (Stage 14). Gating the option tools behind a
committed hypothesis scored 31/77 — worse, though not significantly
(McNemar p = 0.63). But it bought a second measurement, and that is the real
result:

| | |
|---|---|
| diagnosed the right kind of bug | **59/77 (76.6%)** |
| of those, produced the exact repair | 31 (53%) |
| of the 18 wrong diagnoses, exact repair | **0** |

**The agent knows what broke roughly twice as often as it knows how to put it
back.** On the hand-authored hard case it wrote, before seeing any option, that
"the failure is a circular key dependency… the third small key and boss key are
in room 13, beyond the gate" — correct and precise — and then proposed removing
the gate instead of returning the key.

Three arms drove the unlock bias down monotonically (48 → 40 → 36) and intent
recovery went 34, 34, 31. Every intervention changed *which* cases were right;
none changed how many. See [CHANGELOG.md](CHANGELOG.md) Stages 13–14.

## Reproducing

See [REPRODUCE.md](REPRODUCE.md) for clean-environment setup, exact commands,
expected output, runtime, and cost.

## Understanding it

[GUIDE.md](GUIDE.md) is the deep explanation: architecture, a module-by-module
walkthrough, the solver's state design, every significant decision with the
alternative it displaced, and a reading list for the fields this borrows from
(procedural content generation, automated program repair, mutation testing).

## Improvement changelog

[CHANGELOG.md](CHANGELOG.md) records what was tried at each stage, the evidence,
and what was kept, revised, or thrown out — including the experiment that
killed the original design, and the one that made the baseline harder to beat.

## Limitations

- **The graphs carry no coordinates.** VGLC room graphs record connectivity,
  not geometry, so "these rooms are next to each other" is approximated by hop
  distance. A generator with real room positions would give the agent a much
  stronger locality signal — and would also make some heuristics stronger.
- **One edit per case.** Corruptions are single mutations, and repairs are
  single edits. Compound breakage is not covered.
- **Zelda-family mechanics.** Small keys, boss keys, key items, switches. A new
  mechanic needs solver rules today.
- **Intent recovery is exact-match** against the seeded edit. A repair that is
  arguably as good as the original but different scores zero. This is strict on
  purpose — it is the only version of the metric that cannot be argued with.

## What was built when

Everything in `src/`, `tests/`, `scripts/` and the documentation was written
during the hackathon. Pre-existing: the VGLC corpus (MIT, fetched not vendored),
and the libraries in `pyproject.toml`. Claude Code was used as the coding agent
throughout; see [CHANGELOG.md](CHANGELOG.md) for how, and `eval/traces/` for the
repair agent's own trajectories.

## Licence

Code: MIT. The corpus is MIT and belongs to its authors; it is downloaded by
`scripts/fetch_data.sh`, not redistributed here.
