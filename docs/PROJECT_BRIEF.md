# Project Brief: Procedural Level Playability Checker and Auto Fixer

Status: the dataset has been cloned and the core assumptions tested by running real solvers against it. Sections marked **Verified** rest on measurements, not estimates. The evaluation design has changed as a result — see "What the measurements changed".

## The hackathon

This is a submission for the micro1 Agentic Workflows Hackathon, listed on HackerEarth as Frontier Engineering Challenge 2026 (https://www.hackerearth.com/community/challenges/hackathon/micro1-frontier-engineering-challenge-2026/). The full instructions are in docs/micro1 - First Hackathon97ce7c5.pdf.

It's open ended: you pick your own problem in any industry, and every entry needs both a baseline solution and an advanced agent solution, tested on the same task and the same test cases. Using a coding agent is required, not optional, and you need to disclose which tools you used and submit representative agent trajectories.

It's solo, running about 75 hours from August 28th 15:00 UTC to August 31st 18:00 UTC 2026.

Judging is out of 100 points. Problem and User Value is worth 15, Agent Solution and Engineering is worth 30, End to End Quality is worth 20, Measured Improvement is worth 15, Reproducibility is worth 15, and Hot Take or Insights is worth 5. Before any of that scoring happens, submissions go through a qualification gate checking eligibility, completeness, integrity, the agent trace, and reproducibility, so a project that can't actually be run or verified gets disqualified before the rubric even applies. If scores tie, it comes down to Agent Solution and Engineering first, then Reproducibility, then Measured Improvement, then End to End Quality.

A few ground rules worth keeping in mind while building: be clear about what existed before the hackathon and what you built during it, respect the license and terms of every tool and dataset used, keep any consequential action inside a sandbox with human approval, only use data that's legal and either public or synthetic, keep credentials out of the submission entirely, connect every claim back to actual evidence, and make sure the whole thing is reproducible from a clean environment.

Also worth remembering: by registering, the Participation Agreement gives micro1 the right to use submissions for AI model training and evaluation, so keep that in mind for what goes into the repo.

The deliverables are the complete code plus a README explaining the user, their bottleneck, and why it matters, along with an Improvement Changelog listing each stage, what was tried and why, the evidence gathered, and the decision made, ending with the main failure mode and a hot take. Also needed: a reproduction guide written for a clean environment with exact commands, expected output, and approximate runtime and cost; a video of five minutes or less; and representative trajectories from every agent used.

The stack is Python, litellm, and Claude Code.

## The problem

Solo and indie developers who build procedurally generated levels, think dungeon crawlers or Zelda style dungeons with keys and locked doors, occasionally ship levels that can't actually be won. A key ends up placed behind the door it's supposed to open, or part of the map gets cut off entirely. Right now, teams either playtest every seed by hand, which doesn't scale, or fall back on rejection sampling: regenerate the whole level from scratch until one happens to pass. That throws away the entire hand tuned layout and tells you nothing about what was actually wrong.

A basic flood fill only tells you whether there's any open path at all. Once keys, locks, and switches are involved, whether a room is reachable depends on what the player is carrying and what state the world is in, so it becomes a search problem over player state rather than plain reachability, and it's something studios tend to build from scratch for each project rather than reuse.

The sharper version of the problem, established by measurement rather than assumed: **detecting and repairing unplayability is the easy half.** A deterministic search repairs every corrupted level tested, with no model involved. What it cannot do is choose a repair a designer would accept. A broken corridor gets "fixed" by connecting two unrelated rooms on opposite sides of the dungeon. The level passes the check and is still unshippable. The scarce resource is not correctness, it's design intent, and that is where the agent earns its place.

## Why this idea

Before settling on this, existing tools were checked. Chess coaching, crash and bug triage, visual regression testing, design to code diffing, and mod conflict resolution for a specific game like Skyrim, where a tool called LOOT already handles it, are all covered well by mature existing products, so those were ruled out. Checking whether a procedurally generated level is actually playable, across arbitrary mechanics, isn't something any generic tool does. Studios either write their own checker from scratch or fall back on rejection sampling. That gap is why this idea made the cut.

Worth naming honestly in the README: constraint based generation using Answer Set Programming (clingo) sidesteps this entirely by generating only solvable levels by construction. It is the strongest alternative approach and should be cited. The reason this project does repair instead is that ASP cannot repair an existing hand tuned level while preserving what the designer already built, which is exactly the case this targets.

## The data — Verified

The dataset is the Video Game Level Corpus, at github.com/TheVGLC/TheVGLC, MIT licensed, containing real levels pulled from shipped games.

**Use all three Zelda folders, not one.** They share an identical legend file:

| Folder | Dungeons |
|---|---|
| `The Legend of Zelda` | 18 |
| `The Legend of Zelda - Link to the Past` | 12 |
| `The Legend of Zelda - Link's Awakening` | 8 |
| **Total** | **38** |

This matters for mechanic coverage. Boss keys (`K`) and numbered switches (`S1` through `S12`) appear **only** in Link to the Past and Link's Awakening. Base Zelda has zero boss keys and two switch instances, so building on it alone leaves the boss-key and switch logic completely untested.

`Graph Processed/*.dot` are Graphviz DOT files holding the room graphs — nodes are rooms with type labels, edges are passages with lock labels. This is directly machine readable; no tile or pixel parsing is required. `Original/` is reference images only. `Processed/` is tile maps, not needed for this approach.

`zelda.json` defines room types (enemy, switch, boss, key, boss key, key item, puzzle, start, triforce) and door types (switch locked, bombable, key locked, boss key locked, key item locked, soft locked, impassable).

Known data defects to handle:

- The legend is incomplete. Node symbols `i` and `m`, and edge symbol `O`, appear in the data but are undocumented. They are non-blocking and can be carried through as opaque room contents.
- Transcription typos exist: `ep` and `ei` (missing commas), and numeric node labels leaking into Link to the Past.
- Parsing gotcha: the obvious regex for node statements also matches the target of edge statements. Blank out the `->` statements before matching nodes, or every node label will be silently overwritten with an edge label.

Ruled out: **gym-pcgrl cannot cross-validate this solver.** Its `zelda_prob.py` is an 11x7 tile grid with a single key and a single door, scored by Dijkstra path length. Different representation, different mechanics, no key economy. Reproducing 31 of 38 shipped dungeons is a stronger correctness argument anyway.

Also checked and ruled out: HuggingFace has no better dataset for lock-and-key dungeon graphs. If the project ever needs to pivot to a different mechanic, `AlignmentResearch/boxoban-astar-solutions` (Apache 2.0) is the best fallback, since it ships A* solutions as ready made ground truth.

## The solver — Verified

Deterministic, no LLM. It searches over player state and returns a certain pass or fail plus the solution path.

Two things had to be established by experiment, and both are load bearing:

**Soft locked doors are passable.** 62 doors carry the `l` label in *both* directions (that figure counts base Zelda only; across all three games it is 101 — see docs/DATA_NOTES.md), so it cannot mean impassable. Treating it as blocking collapses verified solvability from 31/38 to 6/38.

**State must include which doors are already open.** Room plus keys held plus switches is under specified — small keys are fungible and consumed, so which door you spend a key on changes the outcome. The working state is: current room, collected-key-room bitmask, opened-door bitmask, and flags for key item, boss key, and each switch. Tracking collected rooms as a plain set is exponential and hangs on a 62 room dungeon; bitmasks over only the relevant rooms and doors keep every dungeon under a second.

Result with correct semantics: Zelda 18/18, Link to the Past 6/12, Link's Awakening 7/8 — **31 of 38 shipped dungeons verify as solvable.**

The 7 failures are genuine transcription errors in VGLC, not solver bugs. Link to the Past dungeon 3 encodes one small key but three key-locked doors, all on the critical path, which is unwinnable as transcribed though the shipped game obviously is not. **Restrict the evaluation set to the 31 that verify.** The fact that the tool surfaced real errors in a published research dataset is worth reporting in the changelog.

## What the measurements changed

The original plan was for the agent to diagnose a failure, propose a fix, verify it, and retry. Testing that assumption first is what changed the design.

A deterministic enumerate-and-verify repairer, with no model involved — edit vocabulary of move key, add key, unlock door, add passage, each candidate checked by the solver — produced:

> **35 of 35 seeded corruptions repaired, 100%**, averaging 107 candidates searched, about 1.6 seconds per level, at zero API cost.

So solvability repair is not an agentic problem, and rejection sampling is not an honest baseline to compare against. Shipping the original design would have put an LLM up against a faster, cheaper, deterministic method that wins outright.

The same experiment showed where the real difficulty is:

- **Median 100 valid single-edit fixes per corrupted level** (min 10, max 1371, mean 153).
- The deterministic first-valid fix recovers the designer's actual intended edit **0 of 35 times, 0%**. A random valid pick averages 2.3%.

There are roughly a hundred correct answers per level and choosing well is unsolved. That is the agent's job.

## The architecture

**Level representation.** JSON built from the VGLC room graph: rooms as typed nodes, passages as lock-typed edges, key and item locations.

**Solver.** As above. Built and tested first, since everything depends on it.

**Candidate generator.** Deterministic enumeration over the single-edit vocabulary, each candidate verified by the solver. Produces the full set of provably correct repairs.

**Agent.** Given a failing level, the solver's diagnosis, and the verified candidate set, the agent explains in plain language why the level is broken and selects the repair that best preserves design intent — locality, consistency with existing structure, and the dungeon's difficulty curve — then justifies the choice. Correctness is guaranteed by construction, so the agent is never able to ship an unplayable level; it is spending its judgment only on the question the solver cannot answer.

A human checkpoint asks whether to accept the fix before it is final, in line with the ground rule on supervised consequential actions.

Optional stretch goal, treated as a bonus changelog entry rather than a dependency: handling a brand new lock or mechanic described in a single sentence, without hand coding new solver rules.

## Baselines and evaluation

Test set: the 31 verified-solvable dungeons, corrupted by a fixed-seed script. Corruptions are single mutations — move a key behind its own lock, cut a required passage, add a lock to a free passage. Because corruption is seeded, **the ground-truth inverse edit is known for every case**, which makes the primary metric objective rather than a matter of taste. Target 50 to 100 cases including at least one deliberately hard multi-step key-and-lock chain.

Baselines, in order of honesty:

1. **Rejection sampling** — reroll until the solver passes. Represents what teams do today. Preserves none of the original layout.
2. **Single-prompt LLM** — level JSON in, verdict and fix out, no solver access. Tests whether a model can do this unaided.
3. **Enumerate and take the first valid fix** — the deterministic repairer. This is the baseline that matters. It scores 100% on solvability and 0% on intent, and it is the one a judge will think of.

Metrics:

- **Primary: intent recovery rate** — does the chosen fix match the known ground-truth edit, among fixes that all pass the solver.
- **Solvability** — pass/fail gate that both the agent and baseline 3 clear by construction, reported so the comparison is legible.
- **Layout preservation** — how much of the original structure survives, where rejection sampling scores near zero.
- **Cost and wall time per level.**

Each meaningful change goes into the changelog as it happens, not reconstructed afterward. The measurement that killed the original design belongs there as a kept failed experiment.

**Hot take candidate:** automated repair passes the check and still ships garbage. The constraint solver was never the bottleneck — with a hundred provably correct fixes available, verification is free and judgment is the scarce thing.

## Setup

Python 3.10 or later, a virtual environment, litellm, optionally networkx, and pytest for the evaluation harness. An LLM API key, used through litellm, kept as an environment variable and never committed. A clone of the TheVGLC/TheVGLC repository for the data.

## Next steps

1. Write the DOT parser (watch the edge-target regex trap) and the level JSON schema, across all three Zelda folders.
2. Write the solver with the verified semantics, and assert it reproduces 31/38 as a regression test.
3. Write the seeded corruption script; generate the evaluation set from the 31 verified dungeons, recording the ground-truth inverse edit for each case.
4. Write the candidate generator and confirm it still repairs 100% of corruptions.
5. Build the three baselines and record their intent-recovery scores.
6. Build the agent selection layer, logging every tool call from the start so trajectories are captured automatically rather than reconstructed.
7. Run the full evaluation, write the changelog, README and reproduction guide, record the video, package the trajectories.
