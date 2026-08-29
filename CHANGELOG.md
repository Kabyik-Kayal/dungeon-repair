# Improvement Changelog

Written as the work happened, not reconstructed afterwards. Every row's
evidence is a command in this repository or a file under `eval/`.

All twelve stages are complete; every number below was produced by a command in
this repository, and the results it cites live in `eval/results/`.

---

### Stage 1 — Choose a problem that a tool does not already solve

**Tried.** Audited candidate problems against existing products before writing
any code. Chess blunder coaching, crash triage, visual regression testing,
design-to-code diffing, and mod load-order conflicts are all covered by mature
tools (Chess.com Game Review, Sentry, Percy/Chromatic, LOOT).

**Evidence.** Each of those has a free or standard product that does both
detection *and* the fix.

**Decision — kept.** Playability checking for arbitrary lock-and-key mechanics
has no generic tool; studios write bespoke checkers or reroll. Constraint-based
generation (ASP/`clingo`) sidesteps the problem by generating only solvable
levels, and is cited in the README as the strongest alternative — it cannot
repair an existing hand-tuned level, which is the case this targets.

---

### Stage 2 — Parse the corpus

**Tried.** The obvious regex for DOT node statements, `(\w+) [label="..."]`.

**Evidence.** It also matches the *target* of an edge statement, because
`7 -> 8 [label="k"]` ends in the same shape. Every room's contents were being
silently overwritten by the label of the last edge pointing at it. Nothing
crashed; the graph was just wrong.

**Decision — revised.** Blank out edge statements before matching nodes.
Locked in by `tests/test_parser.py::test_edge_targets_do_not_overwrite_room_labels`.

---

### Stage 3 — Solver semantics: what does a soft lock mean?

**Tried.** Treating the legend's "soft locked" door (`l`) as impassable.

**Evidence.** Only **6 of 38** shipped dungeons came out winnable. 101 doors in
the corpus carry `l` in *both* directions, which cannot mean impassable —
that would wall off the room from itself. Treating it as passable gives
**31 of 38**.

**Decision — revised.** Soft locks are passable. This one flag moves the
headline number by 25 dungeons, so it is asserted in
`tests/test_solver.py::test_shipped_corpus_regression`.

---

### Stage 4 — Solver state: what has to be in it

**Tried.** State as `(room, keys held, switches)`.

**Evidence.** Under-specified. Small keys are fungible and consumed, so
spending one on the wrong door changes the outcome; the search would report a
level winnable that is not. Adding the set of collected rooms fixed
correctness and made a 62-room dungeon hang — the state space is exponential
in a Python `set`.

**Decision — revised.** `(room, collected-key bitmask, opened-door bitmask,
flags)`. Every one of the 38 dungeons now resolves in well under a second;
the whole corpus verifies in 0.5s.

---

### Stage 5 — Test the core assumption before building on it

**Tried.** The original design: agent diagnoses the failure, proposes a fix,
verifies it, retries on rejection. Before building it, the null hypothesis was
measured — enumerate every single edit in the vocabulary (move key, add key,
unlock, add corridor) and ask the solver about each.

**Evidence.** It repaired **every** seeded corruption, at ~100 candidates
searched, ~1.6s per level, **$0**. `eval/results/00_baseline_probe.txt`.

**Decision — removed.** The original design was deleted before it was written.
An LLM asked to make a level winnable is competing with something faster,
cheaper, and deterministic — and losing on all three. The same run showed where
the difficulty is: a **median of 60 valid repairs per broken level** (max 612),
so "which one" is unsolved even though "does one exist" is trivial.

The architecture inverted: solver as oracle, enumeration as candidate
generator, agent as the thing that chooses and justifies. Correctness became a
property of the harness rather than a hope about the model.

---

### Stage 6 — Make the baseline harder to beat, on purpose

**Tried.** First measurement of the deterministic repairer used an arbitrary
enumeration order (keys first). Intent recovery: **0%**. That number was
tempting and wrong to publish.

**Evidence.** The order was doing the damage, not the method. Re-ranked
least-invasive-first — unlock, move key, add key, add corridor, which is what
an engineer would actually reach for — and intent recovery jumped to **33.8%**.

**Decision — kept the stronger baseline.** It cuts the headline gap the agent
has to clear by a third. A baseline chosen to lose is not evidence. The
by-kind breakdown also became the real finding: 25/31 on spurious locks,
**1/46** on everything else.

---

### Stage 7 — The evaluation set was quietly unbalanced

**Tried.** Sampling corruption kinds uniformly per level.

**Evidence.** 55 severed corridors, 21 spurious locks, 7 displaced keys.
Cutting a corridor breaks a dungeon far more often than moving a key does, so
uniform sampling of *attempts* produces a lopsided set of *cases* — and buried
the displaced key, which is the failure the problem statement is actually
about.

**Decision — revised.** Round-robin over kinds with a retry budget per kind.
Now 31 / 31 / 15 across 77 cases.

---

### Stage 8 — Two bugs the tests found, one of which had corrupted a number

**Tried.** Canonicalising door edits so `unlock(5,3)` and `unlock(3,5)` are the
same answer, and inverting a displaced key with a single move.

**Evidence.** The canonicalising swap overwrote `a` before reading it, so
`unlock(5,3)` became `unlock(3,3)` — every door repair on a descending room
pair was silently mangled, and intent-recovery comparisons against them failed.
Separately, displacing a key into a room that already held one is not
invertible by a single move: the destination keeps a key it never had.
`tests/test_repair.py` caught both.

**Decision — kept both fixes.** The measured baseline moved from 28.9% to
**33.8%** once the swap was fixed. The earlier figure was an artifact of the
bug, and is corrected here rather than quietly dropped.

---

### Stage 9 — Agent design: hand it the list, or let it ask?

**Tried.** Two options for getting ~60–600 verified repairs in front of the
model: dump the whole list into the prompt, or expose it behind tools.

**Evidence.** The largest candidate set in the evaluation is 612 repairs, and
a dumped list is both expensive and useless — it answers "what are my options"
and nothing else. The questions that actually separate a good repair from a
verified one are comparative: how far apart are these rooms, what happens to
the key economy, does this collapse the winning route.

**Decision — kept tools.** `diagnose`, `repair_options` (filter by kind, by
room, by hop distance), `compare` (side-by-side analysis, and it accepts
unverified edits so the agent can test its own idea and be told plainly that it
does not work), `room_detail`, `submit`. `submit` refuses anything the solver
has not verified and the refusal returns to the model as feedback, so the loop
is a verification loop and not a suggestion box.

A smaller bug found here: the trace recorder splatted a scored result into an
event that already had a `kind` field, and crashed on collision. Traces are a
deliverable; they now nest the payload.

---

### Stage 10 — Switch providers, and stop hand-copying prices

**Tried.** The default model moved to `openai/gpt-5.6-luna` (litellm makes this
a one-variable change; the agent's tool-calling format is OpenAI-native, so no
translation was needed). Cost accounting was a hand-maintained table of list
prices in `llm.py`.

**Evidence.** litellm's own cost map already knew every model in play and
matched the hand-copied Anthropic figures exactly ($5/$25, $2/$10, $1/$5), so
the local table added a second source that could only drift. It also knew
`gpt-5.6-luna` — including that it supports tool calling, which the agent
requires and which is the one capability that would have failed silently 77
times.

Then a rate probe returned **$0.40 / $1.80** per 1M tokens where the true base
rate is **$0.20 / $1.20**. The cause: this model doubles its input rate above
272k tokens, and the probe had asked for a million-token quote, reading off a
tier this workload never reaches.

**Decision — revised.** Pricing now comes from litellm's map, versioned with
the pinned library, with `PRICE_OVERRIDES` left as an escape hatch for a model
it does not know. Spend is computed from actual per-call token counts, so
tiered pricing is applied correctly without special-casing; only the headline
rate shown to humans needed fixing, and it now samples at 1k tokens. An unknown
model still reports `n/a` rather than a guess.

Added `dungeon-repair check-model`: one cheap call that confirms credentials,
the model string, and tool calling, and prints what that call cost. The two
model-backed methods are the only steps in the whole pipeline that spend money,
and every way they can fail is a way that fails identically 77 times.

---

### Stage 11 — Full evaluation run

**Tried.** All four methods over the same 77 cases, `openai/gpt-5.6-luna`,
4 workers.

**Evidence.**

| method | solvable | intent | layout | s/case | $/case |
|---|---|---|---|---|---|
| rejection | 77/77 | 0/77 (0.0%) | 0.034 | 0.00 | $0 |
| single prompt | 61/77 | 23/77 (29.9%) | 0.961 | 29.9 | $0.0035 |
| first valid | 77/77 | 26/77 (33.8%) | 0.965 | 0.06 | $0 |
| **agent** | **77/77** | **34/77 (44.2%)** | 0.969 | 32.5 | $0.0050 |

**Decision — kept.** The agent beats the strongest baseline by eight cases,
33.8% to 44.2%, and never ships an unplayable level. Full run cost $0.66.

Two things the headline hides, both worth more than the headline:

The single-prompt baseline **ships 16 unwinnable levels out of 77**. Its 29.9%
intent score is within a few points of the deterministic repairer, which makes
it look competitive; it is not, because a fifth of its answers are broken. This
is the clearest evidence in the project that intent recovery must be read next
to the solvability gate, never alone.

The agent's gain is not spread evenly. On spurious locks it scores 26/31
against the baseline's 25 — statistically nothing. Its whole advantage is
severed corridors, 1/31 to 8/31. On displaced keys every method scores zero.

---

### Stage 12 — Hardening after the first full run

**Tried.** During the run I misread its progress as a hang — two cases still
in flight at 20 minutes, the process at 0% CPU — and killed it. Both readings
were wrong: trace timestamps are relative to each case's own start, not wall
clock, and 0% CPU is what a process blocked on network I/O looks like. The run
had already completed and written all 77 rows; the kill hit a finished process
and changed nothing.

**Evidence.** `eval/results/agent.jsonl`: 77 rows, zero errors, written by the
run itself.

**Decision — kept a fix for a bug that had not fired.** The false alarm
surfaced a real fragility: `litellm.completion` was called with no timeout, and
results are only written after every case finishes. One genuinely hung request
would therefore discard an entire completed run. The client now sets a 120s
per-request timeout and 2 retries. No run has hung; this is insurance on a
failure whose cost is everything.

---

### Stage 13 — The reorder experiment: a clean null result

**Tried.** Stage 11 found the agent choosing `unlock` on 48 of 77 cases when
only 31 cases call for one. Three biases were identified in our own code, all
pointing the same way:

1. `repair_options` returned candidates in enumeration order — which is
   `unlock` first, because that order exists to strengthen the deterministic
   baseline — and then **truncated to the first 25**. On cases with many
   unlocks, the agent never saw the alternatives at all.
2. The system prompt's "restore, do not invent" rule used *unlocking a door* as
   its first worked example.
3. `unlock` clears **every** requirement on a door, not just a small-key lock,
   and nothing told the agent that. Nine of its 48 unlocks demolished
   deliberate structure: seven impassable walls, a boss-key door, a key-item
   gate.

The intervention: balanced round-robin sampling across kinds instead of
truncated enumeration order; a neutral wording of the restore rule; and an
explicit warning on any `unlock` that would remove more than a key lock.
Enumeration order itself was left untouched so the baselines stay comparable
and the candidate set stays identical.

**Evidence.**

| | v1 (unlock-first) | v2 (balanced) |
|---|---|---|
| intent recovery | 34/77 | **34/77** |
| solvable | 77/77 | 77/77 |
| chose `unlock` | 48/77 | 40/77 |
| destructive unlocks | 9 | 8 |
| `displaced_key` | 0/15 | 1/15 |
| `severed_corridor` | 8/31 | 9/31 |
| `spurious_lock` | 26/31 | 24/31 |

The de-biasing worked on its own terms — unlock choices fell by eight, exactly
as intended. **The score did not move at all.** Eight cases changed verdict:
four gains, four losses, net zero, which at n=77 is indistinguishable from
noise in either direction.

The losses are the finding. All four were `spurious_lock` cases where the truth
*was* an unlock, and in every one the agent switched to `move_key`:

```
LoZ2_2#2  truth=unlock(16,17)   v1=unlock(16,17)  ->  v2=move_key(16,17)
LoZ2_4#2  truth=unlock(12,13)   v1=unlock(12,13)  ->  v2=move_key(14,12)
LoZ_5#2   truth=unlock(10,8)    v1=unlock(10,8)   ->  v2=move_key(9,8)
LttP_6#3  truth=unlock(15,17)   v1=unlock(15,17)  ->  v2=move_key(17,15)
```

We did not remove a bias. We swapped one for another. The agent redistributed
its answers to match the new shape of the menu and got the same number right.

Even the explicit warnings barely landed: destructive unlocks fell only from 9
to 8, so the agent kept demolishing walls while being told in the option list
that it was doing so.

**Decision — kept, and counted as a failed experiment.** The changes stay
because each is defensible without reference to the score: a list that
truncates away whole categories of option is a genuine defect, and a tool that
can demolish a wall should say so. It is also 16% faster (27.4s vs 32.5s per
case). But it bought **zero** measured improvement, and pretending otherwise
would be the exact sin this changelog exists to avoid.

Cost of the experiment: $0.40.

---

### Stage 14 — Diagnosis-first: the experiment that explained the other two

**Tried.** Stage 13 showed the agent's answer tracking tool prominence rather
than evidence. The remaining hypothesis was that it never had to form a view:
`repair_options` was available from turn one, so it could browse first and
reason afterwards. So the option tools were **gated behind a commitment**. The
agent must call `hypothesise(repair_kind, rooms, reasoning)` — predicting the
bug in the vocabulary it already had, so no new information is leaked — before
`repair_options`, `compare` or `submit` will answer. Revision is allowed; the
*first* hypothesis is what gets scored.

This buys a second, independent measurement: what the agent believed **before
it saw a single option**, scored separately from what it finally did.

**Evidence.**

| arm | intent | chose `unlock` | $/run |
|---|---|---|---|
| v1 unlock-first | 34/77 | 48 | $0.38 |
| v2 balanced | 34/77 | 40 | $0.40 |
| **v3 diagnose-first** | **31/77** | **36** | $0.45 |

Gating made it *worse* — 31 against 34 — though exact McNemar on the 17
discordant pairs gives **p = 0.63**, so the drop is not distinguishable from
chance. Three arms, three interventions that each reduced the unlock bias
monotonically (48 → 40 → 36), and a score that never moved outside 31–34.

The decomposition is what the arm was really for:

```
diagnosis correct (predicted kind == actual kind):  59/77 = 76.6%
  of those 59, the exact repair followed:           31     = 53%
  of the 18 wrong diagnoses, exact repair:           0     =  0%
```

And the confusion matrix, guessed against actual:

```
guessed        move_key  add_door    unlock   total
move_key              8         0         3      11
add_key               0         0         3       3
unlock                7         5        25      37
add_door              0        26         0      26
actual               15        31        31
```

**Decision — kept as an opt-in arm, not as the shipped default.** `--diagnose-first`
reproduces it; the default reproduces the 34/77 headline. The prompt and tool
list switch together with the flag, so the default arm is byte-identical to the
one that produced the shipped numbers.

Three things this settles that two arms could not:

**The agent diagnoses far better than it repairs.** 76.6% versus 40.3%. It
usually knows what kind of thing went wrong. The gap between those two numbers
— 28 cases where it diagnosed correctly and still picked the wrong repair — is
the actual problem, and it is not a diagnosis problem at all.

**A wrong diagnosis is unrecoverable: 0 of 18.** Diagnosis is a hard gate, not
a soft prior.

**Gating removes a lucky path.** Ungated, the agent could browse and stumble
onto the right repair without ever having reasoned to it. Forcing commitment
first makes it more principled and slightly less accurate. That is a real
tension and worth stating: the arm that reasons better scores worse.

The displaced key, the failure this project opened with, moved 0 → 1 → 2 across
the three arms. Under gating the agent diagnosed 8 of 15 displaced keys
correctly and converted 2 of them. It knows the key moved. It cannot work out
which room it came from.

Cost: $0.45.

---

## Main failure mode

**The agent knows what broke and cannot work out how to put it back.**

Three arms and an instrumented diagnosis step narrow it to one number. Asked to
commit to the *kind* of bug before seeing any repair, the agent is right
**76.6%** of the time. Asked to produce the exact repair, it is right **40.3%**
of the time. The 28 cases in between — diagnosed correctly, repaired wrongly —
are the failure.

Displaced keys show it most sharply. Under gating the agent identified 8 of 15
correctly as a misplaced key and converted 2. On the hand-authored hard case it
wrote, before seeing a single option, that "the failure is a circular key
dependency: rooms 10 and 11 provide the first two keys, but the third small key
and boss key are in room 13, beyond the gate" — a correct and precise diagnosis
— and then proposed removing the gate rather than returning the key. It
diagnosed a stranded key and prescribed demolition.

Two earlier explanations were tested and rejected, which is why this one is
worth trusting more:

- *The diagnosis buries the evidence.* No: `_diagnose` already leads with
  `small key(s) in room(s) 24, 25, 30 cannot be collected`, ahead of the door
  list.
- *The option list biases the choice.* Partly, but not decisively: rebalancing
  it moved unlock choices 48 → 40 and the score not at all.

What remains is that identifying a bug and identifying its inverse are
different skills, and this system only has the first. Choosing the room a key
came from requires reading the dungeon's design rhythm — the alcove pattern,
where a key "belongs" — and nothing in the tools exposes rhythm. They expose
distance, topology, and key counts.

## Hot take

**A score that survives every intervention you throw at it is not stable — it
may just be insensitive to the thing you were changing.**

The architecture is right, and the measurement says so: solver as oracle,
enumeration as candidate generator, agent spending its whole budget on
judgment, 44.2% against a 33.8% deterministic baseline that it can never fall
below on safety. That part held up.

What did not survive contact with measurement was the assumption that the
remaining gap was a *prompting and tooling* problem. Three arms attacked the
agent's most visible bias — a runaway preference for `unlock` — and drove it
down monotonically, 48 to 40 to 36 choices out of 77. Intent recovery went 34,
34, 31. Every intervention changed *which* cases were right. None changed how
many. The churn was large (17 discordant pairs between the last two arms) and
the net was noise (p = 0.63).

Instrumenting the diagnosis explained why. The agent identifies the right kind
of bug 76.6% of the time and produces the right repair 40.3% of the time, and a
wrong diagnosis is fatal 18 times out of 18. The bottleneck was never
diagnosis, and it was never which options it saw first. It is that **naming a
fault and inverting it are different skills**, and every tool we built exposes
the first: distance, topology, key counts. None exposes what a designer
actually reads — the rhythm of the place, the fact that this dungeon puts an
alcove before every gate, so a stranded key *belongs* in the alcove before the
gate it opens.

The generalisable lesson is about method rather than dungeons. If you want to
know whether an agent is reasoning or pattern-matching against its own
interface, do not add capability and watch the score go up. **Perturb the
interface and watch whether the answers move while the score does not.** Ours
moved constantly and scored identically, three times running. That is a
signature, and it is only legible because the ground truth was manufactured
rather than judged — every one of these conclusions rests on knowing the exact
edit that broke each level, which no amount of prompting could have told us.
