# Reproduction guide

Written for a clean machine. Every command is copy-pasteable; expected output
is shown; runtimes are measured on an Apple M-series laptop.

## 0. Requirements

| | |
|---|---|
| Python | 3.11 or newer |
| git | any recent version (used to fetch the corpus) |
| Disk | ~120 MB, almost all of it the corpus |
| API key | only for the two model-backed methods (steps 6 and 7) |

## 1. Get the code and create an environment

```bash
git clone <this-repo> dungeon-repair && cd dungeon-repair
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

`uv` works too and is faster:

```bash
uv venv --python 3.11 && uv pip install -e ".[dev]"
```

Installed: `litellm` (model access), `pytest` (tests). Nothing else.

## 2. Fetch the data

```bash
bash scripts/fetch_data.sh
```

The [Video Game Level Corpus](https://github.com/TheVGLC/TheVGLC) (MIT) is
cloned into `data/TheVGLC/`, not vendored into this repository. Expect:

```
pinned commit: 0e86a8f31f20ecad4eaa5741ff061af88767f7fb
  The Legend of Zelda: 18 dungeon graphs
  The Legend of Zelda - Link to the Past: 12 dungeon graphs
  The Legend of Zelda - Link's Awakening: 8 dungeon graphs
```

Runtime: ~20s on a normal connection. To pin a different commit, set
`VGLC_COMMIT`.

## 3. Verify the solver against shipped dungeons

```bash
dungeon-repair verify
```

Expected — the load-bearing regression:

```
  LoZ   18/18
  LttP  6/12
  LA    7/8
  TOTAL 31/38 shipped dungeons verify as winnable
```

The 7 failures are transcription errors in the corpus, not solver bugs; `-v`
prints the diagnosis for each. Runtime: **~0.5s**. Cost: **$0**.

## 4. Build the evaluation set

```bash
dungeon-repair build-cases          # seeded; --seed 1234 by default
python scripts/make_hard_case.py    # the hand-authored hard case
```

Expected:

```
wrote 76 cases to eval/cases
  displaced_key      14
  severed_corridor   31
  spurious_lock      31
...
wrote eval/cases/spiral_keep_hard.json
  verified repairs:      115 (unlock=3, move_key=10, add_key=10, add_door=92)
```

77 cases in total. Runtime: **~6s**. Cost: **$0**. Fully deterministic — the
same seed gives the same cases, asserted by
`tests/test_repair.py::test_case_set_is_reproducible_from_the_seed`.

The repository ships these case files, so this step reproduces them rather than
creating them for the first time. `git status` should stay clean.

## 5. Run the deterministic methods

```bash
dungeon-repair run rejection
dungeon-repair run first_valid
```

Expected final rows:

```
rejection                 77   77/77      0/77   ( 0.0%)   0.034    0.00        $0
first_valid               77   77/77     26/77   (33.8%)   0.965    0.06        $0
```

Runtime: **~1s** and **~5s**. Cost: **$0** for both.

## 6. Configure model access

```bash
cp .env.example .env
# edit .env: OPENAI_API_KEY=sk-...
```

The default model is **`openai/gpt-5.6-luna`**. Model access goes through
[litellm](https://github.com/BerriAI/litellm), so any provider it supports
works — set `DUNGEON_REPAIR_MODEL` and the matching key:

```bash
DUNGEON_REPAIR_MODEL=openai/gpt-5.6-luna      # default        OPENAI_API_KEY
DUNGEON_REPAIR_MODEL=openai/gpt-5.6           # ~20x the cost  OPENAI_API_KEY
DUNGEON_REPAIR_MODEL=anthropic/claude-opus-5  #                ANTHROPIC_API_KEY
```

The agent needs a model with **tool calling**; the single-prompt baseline does
not. Cost accounting reads litellm's own cost map, which ships with the pinned
version of the library and covers every provider it can call, so prices cannot
drift away from the client actually making the calls. A model litellm does not
know reports cost as `n/a` rather than a guess — add an entry to
`PRICE_OVERRIDES` in `src/dungeon_repair/llm.py` if you hit that.

Note that several models price long context at a higher tier — `gpt-5.6-luna`
doubles its input rate above 272k tokens. Spend is always computed from actual
token counts, so the right tier is applied automatically; nothing in this
workload comes close to that threshold.

## 7. Check the setup before spending anything

```bash
dungeon-repair check-model
```

One cheap call that confirms the credentials resolve, the model string is
valid, and tool calling works, then prints the tokens and exact cost of that
call. Step 8 is the only part of this guide that costs money, and a wrong
model string fails 77 times instead of once.

The first two lines are produced without any network call, so they are exactly
as shown; the token counts and cost below them depend on the model and will
differ:

```
model:     openai/gpt-5.6-luna
base rate: $0.20 in / $1.20 out per 1M tokens

credentials:  ok
tool calling: ok -> report_ready
tokens:       <n> in / <n> out
cost:         $0.0000nn
```

A missing or wrong key instead prints `credentials: MISSING` and names the
environment variable that model's provider expects.

## 8. Run the model-backed methods

```bash
dungeon-repair run agent --limit 5              # short smoke run first
dungeon-repair run single_prompt --workers 4    # then the full set
dungeon-repair run agent --workers 4
```

To reproduce the diagnosis-first arm (Stage 14 in the changelog), which gates
the repair tools behind a committed hypothesis and records what the agent
believed before it saw any option:

```bash
dungeon-repair run agent --workers 4 --diagnose-first
```

The flag switches the prompt and the tool list together, so the default run
above is byte-identical to the one that produced the headline results.

`--workers` runs cases concurrently; per-case wall time is still measured per
case. Both write per-case results to `eval/results/<method>.jsonl` and one
trajectory per case to `eval/traces/`.

`single_prompt` is one call per case; `agent` is typically 3–6 calls per case
with tool results, so its context grows across the run. At the default model's
rates this puts the **full 77-case run in the region of one to two dollars**
for the agent and under twenty cents for the single-prompt baseline — an
estimate from the token rates, not a measurement. The real per-case cost is
recorded in the results files and printed in the comparison table.

## 9. Compare

```bash
dungeon-repair compare
```

Prints the headline table across every method with results on disk, plus intent
recovery broken down by corruption kind.

## 10. Look at one repair end to end

```bash
dungeon-repair repair 'spiral_keep#hard'
```

Prints the broken dungeon, the solver's diagnosis, how many verified repairs
exist, what the deterministic method would pick, then runs the agent and asks
for approval before applying anything. This is the demo path.

```bash
dungeon-repair candidates 'spiral_keep#hard'   # every verified repair, no model needed
```

## 11. Tests

```bash
pytest
```

27 tests, **~30s**, no API key required — the agent loop is exercised with a
scripted model stand-in (`tests/conftest.py`). Tests that need the corpus or the
case set skip cleanly if you have not run steps 2 and 4.

## 12. Read a trajectory

```bash
dungeon-repair trace eval/traces/agent__spiral_keep_hard.jsonl
dungeon-repair trace eval/traces/agent__spiral_keep_hard.jsonl --out trajectory.md
```

Renders instructions, every tool call and result, every rejection and retry, the
human checkpoint, and the final scored outcome.

## Determinism and what varies

| | |
|---|---|
| Corpus | pinned to a commit |
| Case generation | seeded (`--seed`), asserted reproducible |
| Solver, enumeration | fully deterministic |
| Model methods | not deterministic. Current Claude models reject sampling parameters, so `temperature=0` is not available; run-to-run variation is real and the trajectories are recorded so any individual result can be inspected |
