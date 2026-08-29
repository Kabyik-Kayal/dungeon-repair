.PHONY: setup data verify cases test baselines agent compare clean

setup:
	python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"

data:
	bash scripts/fetch_data.sh

verify:
	.venv/bin/dungeon-repair verify

cases:
	.venv/bin/dungeon-repair build-cases
	.venv/bin/python scripts/make_hard_case.py

test:
	.venv/bin/pytest

baselines:
	.venv/bin/dungeon-repair run rejection
	.venv/bin/dungeon-repair run first_valid

agent:
	.venv/bin/dungeon-repair run single_prompt --workers 4
	.venv/bin/dungeon-repair run agent --workers 4

compare:
	.venv/bin/dungeon-repair compare

clean:
	rm -rf eval/candidates .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
