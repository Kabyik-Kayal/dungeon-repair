# Archived evaluation arms

Every experiment in [CHANGELOG.md](../../../CHANGELOG.md) that produced a full
77-case run, kept so each claim in the changelog can be checked against the rows
that produced it. `../agent.jsonl` is the shipped default and is identical in
configuration to `agent_v2_balanced` here.

Trajectories for each arm are in `eval/traces/archive/<arm>/`, one file per case.

| arm | stage | intent | solvable | key | corridor | lock | cost |
|---|---|---|---|---|---|---|---|
| `agent_v1_unlock_first` | 13 | **34/77** | 77/77 | 0/15 | 8/31 | 26/31 | $0.382 |
| `agent_v2_balanced` | 13 | **34/77** | 77/77 | 1/15 | 9/31 | 24/31 | $0.395 |
| `agent_v2_repeat_control` | 15 | **32/77** | 77/77 | 0/15 | 9/31 | 23/31 | $0.393 |
| `agent_v3_diagnose_first` | 14 | **31/77** | 77/77 | 2/15 | 7/31 | 22/31 | $0.454 |
| `agent_v4_route_bypass` | 16 | **33/77** | 77/77 | 0/15 | 8/31 | 25/31 | $0.322 |
| `agent_v5_memory_and_notes` | 16 | **35/77** | 76/77 | 2/15 | 7/31 | 26/31 | $0.449 |
| `agent_v5_memory_and_notes_repeat` | 16 | **34/77** | 77/77 | 1/15 | 6/31 | 27/31 | $0.433 |
| `agent_v6_memory_gated` | 16 | **34/77** | 77/77 | 1/15 | 7/31 | 26/31 | $0.385 |
| `agent_v7_unlock_note_only` | 16 | **36/77** | 77/77 | 3/15 | 9/31 | 24/31 | $0.398 |
| `agent_v7_unlock_note_only_repeat` | 16 | **34/77** | 77/77 | 1/15 | 7/31 | 26/31 | $0.412 |

## What each arm was

**`agent_v1_unlock_first`** — Stage 13. First full run. `repair_options` returned candidates in enumeration order and truncated to 25, so whole categories of option were invisible.

**`agent_v2_balanced`** — Stage 13. Balanced round-robin sampling across kinds, neutral wording of the restore rule, explicit warning on a destructive `unlock`. **This is the shipped default** — the same configuration as `../agent.jsonl`.

**`agent_v2_repeat_control`** — Stage 15. The shipped configuration re-run **unchanged**. The variance control, and the most useful run in the project: it establishes the noise floor at eight flipped cases.

**`agent_v3_diagnose_first`** — Stage 14. `--diagnose-first`. Option tools gated behind a committed `hypothesise` call, which buys a separately-scored diagnosis.

**`agent_v4_route_bypass`** — Stage 16. **Superseded design.** Answered the forced cases *without* calling the model. Kept as the evidence for why it was rejected: an agent bypassed is an agent not evaluated.

**`agent_v5_memory_and_notes`** — Stage 16. `--route --memory`. Design memory plus both candidate-set notes.

**`agent_v5_memory_and_notes_repeat`** — Stage 16. Same configuration, second run.

**`agent_v6_memory_gated`** — Stage 16. `design_rhythm` offered only where a key edit is legal. Tests the first pre-registered prediction, which was falsified.

**`agent_v7_unlock_note_only`** — Stage 16. Doors-only note removed. **The Stage 16 configuration `--route --memory` reproduces today.** Tests the second prediction.

**`agent_v7_unlock_note_only_repeat`** — Stage 16. Same configuration, second run. Falsified the second prediction: the 36 did not repeat.

## Reading these

The agent is not deterministic. Two runs of the same configuration differ by
about eight cases and pick the identical repair on roughly 60% of them, so no
single row here supports a claim on its own — see Stage 15. The one result that
reproduces across every Stage 16 arm is the subset where the solver certifies
exactly one `unlock`: 18 and 19 without the note, 21 in all five runs with it.
