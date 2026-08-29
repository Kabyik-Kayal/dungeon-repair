# Guide

A working explanation of this project: what it is for, how it is built, why it
is built that way, and what to read if you want to understand the fields it
borrows from.

The other documents have narrower jobs. [README.md](README.md) is the pitch and
the results. [CHANGELOG.md](CHANGELOG.md) is the chronological record of what
was tried and what the evidence said. [REPRODUCE.md](REPRODUCE.md) is the
command list. [docs/DATA_NOTES.md](docs/DATA_NOTES.md) is the corpus autopsy.
This guide is the one that explains the machine.

---

## 1. What we are trying to achieve

### The user

A developer who generates game levels procedurally and cannot hand-check every
seed. Dungeon crawlers, roguelikes, metroidvanias — any design where progress
is gated by keys, switches, and locked doors.

### The failure

A generated dungeon can be structurally sound and still impossible to finish:

- the key for a door generates behind that door
- a corridor is dropped and a wing is orphaned
- three locked doors sit on the critical path and only two keys were placed

None of these are visible to a connectivity check. Once keys are **consumed**,
reachability stops being a property of the graph and becomes a property of the
player's state: which rooms you have visited, what you are carrying, what you
have already spent. A room reachable with two keys in hand may be unreachable
if you spent one on the wrong door ten rooms ago.

### What the industry does today

Two things, both bad:

1. **Playtest every seed by hand.** Correct, and it does not scale.
2. **Reject and reroll.** Generate, check, discard, repeat until one passes.
   Cheap, scales fine, and throws away the entire hand-tuned layout. You learn
   nothing about what was wrong.

### What we set out to build

A tool that (a) proves whether a level can be finished, and (b) when it cannot,
repairs it in a way its designer would accept — preserving the layout rather
than regenerating it.

Half of that goal turned out to be trivial. That discovery is the project.

---

## 2. The central insight

The original plan was the obvious one: an agent diagnoses the failure, proposes
a fix, verifies it, retries when the fix fails.

Before building it, we measured the null hypothesis. Enumerate every single
edit in a tiny vocabulary — move a key, add a key, unlock a door, add a
corridor — and ask a solver about each one.

**It repaired every broken level we tested, deterministically, in under a
second, for zero API spend.**

So "make the level winnable" is not an agentic problem. Any LLM pointed at it
is competing with something faster, cheaper, and provably correct, and losing
on all three axes at once.

The same experiment showed where the difficulty actually lives:

- There is a **median of 60 provably-correct repairs per broken level**
  (minimum 6, maximum 612).
- The deterministic repairer, ranked least-invasive-first, clears the
  solvability gate on **77/77** cases and recovers the designer's intent on
  **26/77**.

It "repairs" a severed corridor by connecting two rooms on opposite sides of
the dungeon. The level passes every check and is unshippable.

> **Correctness is free. Judgment is scarce.**
>
> The solver is the oracle. Enumeration is the candidate generator. The agent
> never has to make the level winnable — it chooses among repairs that are
> already proven correct, and explains the choice.

This inversion is the whole architecture. It has a consequence worth stating
plainly: **the agent is structurally incapable of shipping an unplayable
level**, because the only thing it is allowed to do is pick from a verified
set. It spends its entire budget on the one question the solver cannot answer.

---

## 3. Architecture

```
   data/TheVGLC/**/*.dot
            │
            │  vglc.py — parse Graphviz DOT
            ▼
         Level  ────────────────────────────────┐
     (level.py)                                 │
            │                                   │
            │  corrupt.py                       │  solver.py
            │  seeded single mutation           │  BFS over player state
            ▼                                   ▼
    Case(broken, original, truth)        SolveResult
            │                            winnable? route? blockers?
            │                                   │
            │        candidates.py              │
            └──────► enumerate_edits ───────────┤
                     verify each with solver    │
                             │                  │
                             ▼                  ▼
                      CandidateSet         diagnosis
                    ~60 verified repairs        │
                             └────────┬─────────┘
                                      ▼
                            agent/ (loop.py, tools.py)
                       diagnose · repair_options · compare
                          room_detail · submit(verified)
                                      │
                             human checkpoint
                                      ▼
                        Attempt (metrics.py) + Trace
```

Data flows one way. Nothing downstream of the solver can produce a level the
solver has not blessed.

---

## 4. Module by module

### `level.py` (256 lines) — the representation

A `Level` is immutable: room ids mapped to frozensets of content symbols, plus
a tuple of directed `Passage` objects.

Two decisions matter here:

**Passages are directed.** The corpus has doors that are free one way and
locked the other (`17 -> 15 [label="k"]` alongside `15 -> 17 [label="l"]`).
Collapsing them into undirected doors would silently discard real one-way
structure. A `Passage.door` property gives the canonical undirected pair when
you need it.

**Every edit returns a new `Level`.** `moved`, `with_door_added`,
`without_door`, `with_door_requirements` all copy. The candidate generator
applies thousands of speculative edits per case; mutation would require
defensive copying everywhere or produce heisenbugs.

`outline()` renders the human- and prompt-readable form. It is what the agent
sees.

### `vglc.py` (parser)

Turns `Graph Processed/*.dot` into `Level`s. Small, and it contains the single
nastiest trap in the project:

```python
_NODE = re.compile(r'\b(\w+)\s*\[label="([^"]*)"\]')
```

This also matches the *target* of `7 -> 8 [label="k"]`, because an edge
statement ends in the same shape as a node statement. Every room's contents get
silently overwritten by the label of the last edge pointing at it. Nothing
crashes; the graph is just wrong. The fix is to blank out edge statements
(preserving offsets) before matching nodes.

It also splits the corpus's `ep`/`ei` typos back into `e,p` and `e,i`.

### `solver.py` (251 lines) — the oracle

See [section 5](#5-the-solver-in-depth).

### `edits.py` (82 lines) — the vocabulary

Four edits: `move_key`, `add_key`, `unlock`, `add_door`. One frozen dataclass
with `kind`, `a`, `b`.

The important subtlety is **canonicalisation**. `unlock(5,3)` and `unlock(3,5)`
are the same repair, so `__post_init__` sorts the endpoints for door-shaped
edits — but not for `move_key`, where direction is meaning (`move_key(3,5)` is
not `move_key(5,3)`). Getting this wrong once cost us a wrong headline number;
see Stage 8 in the changelog.

One vocabulary is shared by corruption, enumeration, and the agent. That is
what makes a corruption's inverse expressible as a candidate, which is what
makes intent recovery measurable at all.

### `corrupt.py` (198 lines) — manufacturing ground truth

Applies one seeded mutation and records its inverse:

| corruption | what breaks | recorded truth |
|---|---|---|
| `displaced_key` | a key generates in the wrong room | `move_key(wrong, right)` |
| `severed_corridor` | a free passage is dropped | `add_door(a, b)` |
| `spurious_lock` | a free door becomes key-locked | `unlock(a, b)` |

Two filters make the cases hard rather than incidental:

- A mutation is **kept only if the solver confirms it broke the level.**
  Mutations that hit a redundant corridor or a spare key are discarded, so
  every surviving case sits on the critical path.
- A displaced key may not land in a room that already holds one, because that
  is not invertible by a single move — the destination would keep a key it
  never had, and the case would have no ground truth in the vocabulary.

Sampling is **round-robin across kinds**, not uniform over attempts. Cutting a
corridor breaks a dungeon far more often than moving a key does, so uniform
sampling produces a lopsided case set and buries the displaced key.

### `candidates.py` (120 lines) — the candidate generator

`enumerate_edits` yields the full vocabulary in a fixed order;
`verified_candidates` keeps whatever the solver certifies.

`KIND_ORDER = (UNLOCK, MOVE_KEY, ADD_KEY, ADD_DOOR)` — **least invasive
first.** An unlock or a key move leaves the floor plan intact; adding a key
inflates the key economy; a new corridor rewrites topology. This ordering
exists to make the deterministic baseline as strong as it reasonably can be.
It also, as it turned out, biases the agent — see [section 9](#9-results-and-what-they-mean).

### `topology.py` (58 lines) — structural helpers

Hop distances ignoring locks (pure topology, not reachability), and
`layout_preservation`: Jaccard similarity over doors-with-their-locks plus
room-contents assignments. A single-edit repair scores ~1.0; a regenerated
level scores ~0.03.

### `agent/` — the thing being tested

`prompts.py`, `tools.py` (5 tools), `loop.py` (the verification loop). See
[section 6](#6-the-agent-in-depth).

### `baselines/` — three of them

- `rejection.py` — regenerates a whole dungeon to the same spec (room count,
  door count, key count, lock count) and rerolls until the solver passes. It
  needs a generator, so there is a small one here: random spanning tree, extra
  doors to hit the target count, random placement of start/goal/keys.
- `single_prompt.py` — one model call, the level in, an edit out. No tools, no
  solver. The only method that can ship a broken level.
- `first_valid.py` — the deterministic repairer. The baseline that matters.

### `llm.py` (278 lines) — model access

A thin wrapper over litellm: one place that talks to a model, one place that
counts cost. Notable choices:

- **No `temperature`.** Current frontier reasoning models on both providers
  reject sampling parameters. Determinism here comes from the verified
  candidate set, not from decoding settings.
- **Pricing comes from litellm's cost map**, not a hand-copied table, so it
  cannot drift from the client actually making the calls. `PRICE_OVERRIDES` is
  the escape hatch for a model litellm does not know. Unknown pricing reports
  `n/a` and never a guess.
- **`estimate_cost` uses real token counts.** Several models price long context
  at a higher tier (`gpt-5.6-luna` doubles its input rate above 272k tokens),
  so quoting a rate from a large sample reports a tier this workload never
  reaches.
- **120s timeout, 2 retries.** Results are only written after every case
  finishes, so one hung request would discard an entire completed run.

### `trace.py` — trajectories

Append-only JSONL, written as the work happens rather than reconstructed
afterwards. Records instructions, model turns with token counts, tool calls,
tool results, rejections sent back to the model, the human checkpoint, and the
final scored outcome. `render_markdown` turns one into something a human can
read.

### `metrics.py`, `runner.py`, `cli.py`

Scoring (`Attempt`, `score`, `summarise`), orchestration with a thread pool and
an on-disk candidate cache, and the command line. `runner.py` catches
exceptions per case, so one bad case scores as an error instead of killing a
run.

---

## 5. The solver in depth

This is the component everything else trusts, so it is the one worth
understanding fully.

### Why not flood fill

Because keys are **consumed**. A flood fill answers "is there a path of open
doors", which is the wrong question the moment a small key can be spent on
either of two doors. The real question is: *does there exist an ordering of key
spends and switch flips that reaches the goal?* That is a search over player
state.

### The state

```python
(room, collected_key_mask, opened_door_mask, flags)
```

- `collected_key_mask` — bitmask over rooms that contain a small key
- `opened_door_mask` — bitmask over key-locked doors already opened
- `flags` — bit 0 key item, bit 1 boss key, bits 2+ each switch

Keys in hand is then `popcount(collected) - popcount(opened)`.

**Why opened doors must be in the state.** Small keys are fungible and
consumed, so *which* door you spent a key on changes what is reachable later.
A state of `(room, keys, switches)` is under-specified: it will report a level
winnable that is not, because it cannot distinguish "two keys, spent none" from
"three keys, spent one on the wrong door."

**Why bitmasks and not sets.** Tracking collected rooms as a Python `set`
inside the visited-state key is correct but exponential in practice — it hangs
on the 62- and 66-room dungeons. Bitmasks over only the *relevant* rooms and
doors (there are rarely more than a dozen of each) keep every dungeon in the
corpus under a second. The whole 38-dungeon corpus verifies in 0.5s.

### The two semantics established by experiment

Neither was in the legend; both were established by running the solver against
shipped dungeons and seeing which reading reproduced reality.

**Soft-locked doors (`l`) are passable.** 101 doors carry `l` in *both*
directions, which cannot mean impassable — that would wall a room off from
itself. Treating it as blocking collapses verified solvability from **31/38 to
6/38**. This single flag is worth 25 dungeons.

**Impassable (`s`) really does block**, and note the symbol collision: `s`
means *start* on a room and *impassable* on a door. Symbol meaning depends on
position.

### What it returns

`SolveResult` carries more than a boolean, because the agent needs a diagnosis
and a designer needs an explanation:

- `solvable`, and `reason` when not
- `reachable` / `unreachable` room sets
- `blockers` — passages reached but never traversable, each with a reason
  (`no small key in hand`, `needs the boss key`, `needs switch 3`, …)
- `route` — an actual winning walk, reconstructed from parent pointers
- `expanded` — states searched, so cost claims are checkable

`_diagnose` composes the human-readable failure line. **Its ordering turns out
to matter enormously** — see section 9.

### The regression that guards it

31 of 38 shipped dungeons verify as winnable (LoZ 18/18, LttP 6/12, LA 7/8).
The 7 failures are transcription errors in the corpus, not solver bugs:
`LttP_3` encodes one small key against three key-locked doors, all on the
critical path. `tests/test_solver.py::test_shipped_corpus_regression` asserts
the number. If a semantics change moves it, a test fails.

Reproducing 31 shipped commercial dungeons is the correctness argument. There
is no external solver to cross-validate against — `gym-pcgrl`'s Zelda problem
is an 11×7 tile grid with one key and one door, a different representation with
no key economy.

---

## 6. The agent in depth

### What it is given

The broken level's outline, and five tools. Crucially, it is **not** given the
job of finding a repair — `repair_options` only ever returns repairs the solver
has already certified.

### The tools

| tool | answers |
|---|---|
| `diagnose` | why the dungeon cannot be finished: unreachable rooms, blocking doors, key economy |
| `repair_options` | verified repairs, filterable by kind, by room, by hop distance |
| `compare` | side-by-side analysis of specific repairs |
| `room_detail` | contents, doors, distance from start |
| `submit` | the final choice plus reasoning — **refuses anything unverified** |

`compare` is the one that carries the design judgment. For each repair it
reports hop distance between the rooms involved, whether topology changes, the
key economy afterwards, the new winning route, and how many rooms became
reachable. It deliberately **accepts unverified edits too**, and says plainly
that they do not work — an agent that wants to test its own idea should be able
to.

### The verification gate

`submit` compares against the verified set and raises `ToolError` on anything
else. `loop.py` catches it, returns `Rejected: …` to the model as a tool
result, and the loop continues. This is what makes it a verification loop
rather than a suggestion box, and it is tested:
`test_agent_never_ships_an_unplayable_level` drives a model that only ever
proposes broken repairs and asserts the run ends with no edit rather than a bad
one.

### The human checkpoint

Nothing is applied without approval. Interactive runs (`dungeon-repair repair`)
prompt; evaluation runs auto-approve, and **the trace records which of the two
it was**. This satisfies the hackathon's rule about consequential actions and
costs one line in the loop.

### Prompt design

The system prompt spends no words on correctness, because correctness is
handled. It gives judgment criteria: locality, restore-don't-invent, key
economy, don't trivialise the level, fit the rest of the dungeon. And it asks
for the reasoning step that a designer would do: *work backwards from the
symptom to the bug — what single mistake would produce exactly this failure,
not merely some failure?*

Section 9 covers how well that instruction actually held up. Short version: not
well enough to beat the ordering of the tool output.

---

## 7. Evaluation design

### The problem with evaluating "which fix is best"

It is a taste test. Two repairs both verify; which is better is a judgment
call, and judgment calls cannot be scored without a rubric, and rubrics get
argued with. LLM-as-judge would import exactly the subjectivity we are trying
to measure.

### The solution: manufacture the ground truth

Break a working level with a **known** edit. The intended repair is then known
by construction — it is the inverse of the edit we applied. "Did the method
recover the designer's intent" becomes an objective, exact-match question.

This is a borrowed idea, and worth naming: it is **mutation testing** applied
to level design. Take a correct artifact, inject a seeded fault, and measure
whether your tooling catches and correctly fixes it. The literature in section
11 is directly relevant.

### The case set

77 cases: 76 seeded corruptions across the 31 verified dungeons (balanced
across the three kinds), plus one hand-authored hard case.

**The hard case** (`spiral_keep#hard`) is designed, not sampled. The keep
repeats one rhythm three times — an alcove holding the key for the gate
directly ahead — and the third key generates behind its own gate. 115 repairs
verify. Ten of them move the stranded key. **One** puts it back in its alcove.
The *kind* of bug is obvious; the *choice* is not. That is the point.

### The metrics

- **Intent recovery** (primary) — exact match against the seeded edit.
- **Solvability** — a gate, not an achievement. Reported so the comparison
  stays legible, and so a method that clears it by construction is not
  credited for doing so.
- **Layout preservation** — Jaccard over the structure. Separates a single edit
  from a regeneration.
- **Wall time and cost per case.**

Exact-match is strict on purpose. A repair that is arguably as good as the
original but different scores zero. It is the only version of the metric that
cannot be argued with, and the cost of that strictness shows up honestly in the
results — the agent's near-miss on the hard case (right hall, wrong alcove)
scores zero.

---

## 8. Decisions, and what we rejected

| # | Decision | Why | Rejected alternative |
|---|---|---|---|
| 1 | Repair, not constraint-based generation | ASP (`clingo`) generates only-solvable levels by construction, but cannot repair an existing hand-tuned level | Answer Set Programming — genuinely the stronger approach *for generation*, cited in the README |
| 2 | Room graphs, not tile maps | The corpus ships machine-readable DOT graphs; tiles would add a parsing project with no gain | Parsing `Processed/` tile maps |
| 3 | All three Zelda folders | Boss keys and switches appear **only** in LttP and LA; base Zelda alone leaves that logic untested | Using the 18 base-Zelda dungeons |
| 4 | Restrict eval to the 31 that verify | The other 7 are corpus transcription errors; corrupting an already-broken level has no meaningful ground truth | Using all 38 |
| 5 | Solver as oracle, agent as chooser | Measured: enumeration repairs 100% for $0; the agent would lose that race | Agent proposes fixes and retries until solvable |
| 6 | Least-invasive-first enumeration | Makes the deterministic baseline as strong as it reasonably can be — 0% → 33.8% | An arbitrary order that flattered us |
| 7 | Seeded corruption for ground truth | Makes intent recovery objective instead of a taste test | LLM-as-judge; human rating |
| 8 | Exact-match intent metric | Unarguable | Partial credit / similarity scoring, which reintroduces judgment |
| 9 | Tools over a dumped candidate list | The largest set is 612 repairs; the useful questions are comparative, not enumerative | Dumping all candidates into the prompt |
| 10 | litellm over a provider SDK | Anyone reproducing this can use whatever key they have; provider is one env var | Provider-specific SDK |
| 11 | Pricing from litellm's cost map | One maintained source, versioned with the library, cannot drift from the client | A hand-copied price table (we had one; deleted it) |
| 12 | No `temperature` | Current reasoning models reject sampling params; determinism comes from the verified set | `temperature=0` |
| 13 | Traces written during the run | They are a deliverable; reconstruction after the fact is not evidence | Post-hoc log parsing |
| 14 | Human checkpoint in the loop | Required for consequential actions; costs one line | Auto-apply |

---

## 9. Results, and what they mean

| method | solvable | intent recovery | layout | s/case | $/case |
|---|---|---|---|---|---|
| rejection sampling | 77/77 | 0/77 (0.0%) | 0.034 | 0.00 | $0 |
| single prompt, no tools | **61/77** | 23/77 (29.9%) | 0.961 | 29.9 | $0.0035 |
| enumerate, first valid | 77/77 | 26/77 (33.8%) | 0.965 | 0.06 | $0 |
| **agent** | **77/77** | **34/77 (44.2%)** | 0.966 | 27.4 | $0.0051 |

The agent beats the strongest baseline by eight cases — 33.8% to 44.2%, a 31%
relative gain — and never ships an unplayable level. Full run: $0.65.

**Read the single-prompt row carefully.** Its 29.9% looks competitive with the
deterministic repairer. It is not: **16 of its 77 repairs leave the dungeon
unwinnable.** That is the clearest evidence in the project that intent recovery
must be read next to the solvability gate, never alone.

### The win is narrow

| kind | first valid | agent |
|---|---|---|
| `displaced_key` | 0/15 | **1/15** |
| `severed_corridor` | 1/31 | **9/31** |
| `spurious_lock` | 25/31 | **24/31** |

Its entire advantage is severed corridors, where hop distance is a real signal
and it goes 1 → 9. On spurious locks it is level with the deterministic
repairer, and on displaced keys — the failure the problem statement opens with
— it manages one.

### The failure mode, and the experiment that tested it

On **13 of 15** displaced-key cases the first run's agent did not pick a wrong
destination room — it did not choose `move_key` at all. It chose `unlock`,
which balances the key economy, verifies, and is wrong: the dungeon now has one
fewer locked door than the designer drew and the real key is still in the wrong
room.

**The first explanation was wrong, and checking it mattered.** The intuition
was that `_diagnose` buries the evidence under a blocked-door list. It does
not. On a real case it reads:

```
Why: goal room 5 is not reachable; small key(s) in room(s) 24, 25, 30 cannot
be collected; out of keys at door(s) 20-18; ...
```

The stranded keys come *first*, ahead of the door list. The bug is named, in
plain language, at the front — and the agent reaches past it anyway.

Three real biases did exist, all ours:

1. `repair_options` returned candidates in enumeration order (`unlock` first,
   because that order exists to strengthen the *baseline*) and **truncated to
   the first 25** — so on many cases the alternatives were never shown.
2. The prompt's "restore, do not invent" rule used *unlocking a door* as its
   first worked example.
3. `unlock` clears **every** requirement on a door, not just a key lock, and
   nothing said so. Nine of 48 unlocks demolished deliberate structure — seven
   impassable walls, a boss-key door, a key-item gate.

All three were fixed: round-robin sampling across kinds, neutral wording, and
an explicit warning on any destructive unlock. Enumeration order was left
alone so the baselines stayed comparable.

**The result was a clean null.** Unlock choices fell 48 → 40, exactly as
intended. Intent recovery went 34/77 → 34/77. Four cases flipped to correct,
four flipped to wrong, and every one of the four losses was a `spurious_lock`
case where unlocking was the right answer and the agent switched to `move_key`.

### Diagnosis-first, and what it revealed

The remaining explanation was that the agent never had to form a view:
`repair_options` was available from turn one, so it could browse first and
reason afterwards. So the option tools were gated behind a commitment — the
agent must call `hypothesise(repair_kind, rooms, reasoning)` before
`repair_options`, `compare` or `submit` will answer. It predicts in the edit
vocabulary it already had, so nothing is leaked. Revision is allowed and the
*first* hypothesis is scored. Available via `--diagnose-first`.

It scored **31/77**, worse than 34/77 and not significantly so (McNemar
p = 0.63). But it produced a second, independent measurement:

```
diagnosed the right kind of bug:                   59/77 = 76.6%
  of those 59, the exact repair followed:          31     = 53%
  of the 18 wrong diagnoses, exact repair:          0     =  0%
```

**The agent diagnoses roughly twice as well as it repairs.** The 28 cases where
it diagnosed correctly and repaired wrongly are the real failure, and they are
not a diagnosis problem. A wrong diagnosis, meanwhile, is unrecoverable — 0 of
18 — so diagnosis is a hard gate rather than a soft prior.

Gating also removed a lucky path: ungated, the agent could stumble onto the
right repair without reasoning to it. **The arm that reasons better scores
worse.**

### The control that had to come first

Across three arms the unlock bias fell monotonically (48 → 40 → 36) and intent
recovery went 34, 34, 31. Only after all three was the obvious control run: the
shipped configuration against itself, changing nothing.

| pair | intervention | intent | discordant | same repair |
|---|---|---|---|---|
| v2 vs v2-repeat | **none** | 34 → 32 | **8** | 49/77 |
| v1 vs v2 | rebalanced tools | 34 → 34 | 8 | 46/77 |
| v2 vs v3 | diagnosis gate | 34 → 31 | 17 | 36/77 |

**The agent picks the same repair on only 64% of cases given identical input.**
Changing nothing flips eight cases — the same number the first intervention
flipped. Any conclusion drawn from *which* cases moved between v1 and v2 was
reading the model's own variance.

What survives, because it reproduces: the repeat chose 41 unlocks against v2's
40 and nowhere near v1's 48. Tool presentation reliably changes what the agent
reaches for and reliably fails to change how often it is right.

The practical lessons, in order of how much they would have saved us:

1. **Run the same-config control first.** Not fifth. Without a noise floor, an
   A/B on 77 cases cannot resolve anything smaller than about eight cases, and
   every individually-inspectable flipped case will still have a plausible
   story attached to it.
2. **Perturb the presentation and watch the distribution, not the score.** The
   choice mix moved reproducibly; the score never did.
3. **Instrument the intermediate step.** The gap between 76.6% diagnosis and
   40.3% repair is invisible if you only score the final answer.

## 10. Where to take it next

**Done, and it failed.** Reordering `repair_options` and de-biasing the prompt
changed what the agent picks and not how well it picks — see section 9. The
next experiments have to target reasoning rather than presentation.

**Measure run-to-run variance first.** This is now the highest-value next run
and it is a control, not a feature. All three arms were single runs, so some of
the churn between them is the model's own nondeterminism rather than the
intervention — and sampling parameters are unavailable on current reasoning
models, so it cannot be tuned away. Re-running one arm unchanged and measuring
how many cases flip would put an error bar on every comparison above. Without
it, "17 discordant pairs" cannot be split into signal and noise.

**Expose design rhythm to the agent.** The 28 diagnosed-but-misrepaired cases
are the target. Choosing which room a key came from needs the dungeon's
pattern — this keep puts an alcove before every gate — and no current tool
exposes pattern. A tool reporting structural motifs (rooms whose contents and
degree match a repeating shape) would attack the actual gap rather than the
presentation.

**Room coordinates.** VGLC graphs record connectivity, not geometry, so
"these rooms are adjacent in space" is approximated by hop distance. A
generator with real positions would give a much stronger locality signal — and
would also strengthen the heuristic baselines, which is the honest caveat.

**Compound breakage.** Corruptions are single mutations and repairs are single
edits. Two simultaneous faults are not covered and would need a different
candidate generator (pairs blow up combinatorially — that is where a search
policy, or an agent proposing candidate *pairs*, earns its place).

**New mechanics.** A one-sentence description of a new lock type currently
needs hand-written solver rules. Having the agent extend the solver, with the
existing 31-dungeon regression as the guard, is the natural stretch.

**Partial credit.** Exact match calls the hard-case near-miss (right hall,
wrong alcove) a zero. A distance-weighted secondary metric would show the
agent's progress more faithfully — reported *alongside* exact match, never
replacing it.

---

## 11. Where to learn this

Titles and authors are given rather than DOIs or arXiv numbers, deliberately —
look them up rather than trust an identifier transcribed from memory.

### Procedural content generation, generally

- ***Procedural Content Generation in Games*** — Shaker, Togelius & Nelson.
  The standard textbook, free online at **pcgbook.com**. Start here.
- **"Search-Based Procedural Content Generation: A Taxonomy and Survey"** —
  Togelius, Yannakakis, Stanley & Browne (IEEE ToCIAIG, 2011). The framing
  most PCG work still uses.
- **"Procedural Content Generation via Machine Learning (PCGML)"** —
  Summerville et al. (IEEE Transactions on Games, 2018). Survey; the paper that
  motivated the corpus this project uses.

### The corpus

- **"The VGLC: The Video Game Level Corpus"** — Summerville, Snodgrass,
  Mateas & Ontañón (Proc. PCG Workshop, 2016). The dataset paper.
  Repository: **github.com/TheVGLC/TheVGLC** (MIT).

### Lock-and-key dungeons specifically

This is the sub-field this project sits in, and it is smaller than you would
expect.

- **"Adventures in Level Design: Generating Missions and Spaces for Action
  Adventure Games"** — Joris Dormans (2010). The mission-graph/space-graph
  separation that underlies most Zelda-style dungeon generation. **The single
  most relevant paper to this project.**
- **"Generating Missions and Spaces for Adaptable Play Experiences"** —
  Dormans & Bakkes (IEEE ToCIAIG, 2011).
- **Randomizer "logic" implementations.** The Zelda randomizer communities (A
  Link to the Past, Ocarina of Time) have spent a decade building exactly the
  reachability-under-item-state solvers this project's `solver.py` is a small
  version of. Their open-source logic modules are the best *practitioner*
  resource on the problem, and are largely unpublished academically.

### Constraint-based generation — the road not taken

- **"Answer Set Programming for Procedural Content Generation: A Design Space
  Approach"** — Adam M. Smith & Michael Mateas (IEEE ToCIAIG, 2011). The paper
  behind decision #1.
- **Potassco / `clingo`** — **potassco.org**. The ASP toolchain you would
  actually use.
- **Sturgeon** — Seth Cooper's constraint-based level generation tool
  (AIIDE, 2022 onwards). Modern, practical, actively developed.

### Search and state-space planning

- ***Artificial Intelligence: A Modern Approach*** — Russell & Norvig,
  chapters 3–4 (uninformed and informed search). `solver.py` is a
  breadth-first search over a compound state; this is the chapter that explains
  why that is the right shape.
- **Bitmask state encoding** — the technique that makes it fast. Any
  competitive-programming treatment of "bitmask DP" / "travelling salesman with
  bitmask" covers it; **cp-algorithms.com** is a good free reference.
- **Classical planning / PDDL** — the fully general version of "reachability
  under consumable resources". Worth knowing exists; overkill here.

### Automated program repair — the closest analogue, and the one to read

This project is, structurally, automated program repair for game levels. The
field has already discovered our failure mode and named it.

- **"Automatic Software Repair: A Bibliography"** — Martin Monperrus (ACM
  Computing Surveys, 2018). The map of the field.
- **"GenProg: A Generic Method for Automatic Software Repair"** — Le Goues,
  Nguyen, Forrest & Weimer (IEEE TSE, 2012). Generate-and-validate repair, the
  same shape as `candidates.py`.
- **"Is the Cure Worse Than the Disease? Overfitting in Automated Program
  Repair"** — Smith, Barr, Le Goues & Brun (ESEC/FSE, 2015). **Read this one.**
  It is the same finding as our hot take, a decade earlier and in another
  domain: patches that pass every test and are still wrong. Their "overfitting
  to the test suite" is our "verifies and is still a teleport corridor."

### Mutation testing — where our evaluation method comes from

- **"An Analysis and Survey of the Development of Mutation Testing"** — Jia &
  Harman (IEEE TSE, 2011). Seeded faults with known fixes, which is exactly
  `corrupt.py`.

### Agent engineering

- **"Building Effective Agents"** — Anthropic engineering blog (2024). The
  clearest short statement of when a workflow beats an agent, which is the
  decision behind this project's whole architecture.
- **Anthropic's guidance on writing tools for agents** (engineering blog). Tool
  design as the primary lever — directly relevant to our section 9 failure.
- **"ReAct: Synergizing Reasoning and Acting in Language Models"** — Yao et al.
  (2022). The interleaved reason/act/observe loop `loop.py` implements.
- **"Let's Verify Step by Step"** — Lightman et al. (2023). Verifier-guided
  generation; the general case of "let a checker settle correctness so the
  model can spend its budget elsewhere."
- **"Judging LLM-as-a-Judge…"** — Zheng et al. (2023). Useful precisely for
  understanding what we avoided by manufacturing ground truth instead.

### The libraries

- **litellm** — **docs.litellm.ai**. Provider routing, cost map, `num_retries`,
  `timeout`.
- **pytest** — **docs.pytest.org**. Fixtures and `conftest.py`, which is how
  the agent loop is tested without credentials.
- **Graphviz DOT language** — **graphviz.org/doc/info/lang.html**. What the
  corpus files actually are.

---

## 12. Glossary

| term | meaning here |
|---|---|
| **case** | one broken level plus the known edit that broke it |
| **candidate** | a single edit the solver has certified as making the level winnable |
| **intent recovery** | the chosen repair exactly matches the seeded edit's inverse |
| **layout preservation** | Jaccard similarity of doors-with-locks and room contents against the original |
| **soft lock** (`l`) | a corpus door label that, despite the name, is **passable** |
| **key economy** | the relationship between small keys placed and key-locked doors on the critical path |
| **blocker** | a passage the player can reach but never traverse, with a reason |
| **the gate** | the solvability check — passing it is necessary and nowhere near sufficient |
