import json
from pathlib import Path

import pytest

from dungeon_repair.llm import DEFAULT_MODEL, ModelReply, Usage
from dungeon_repair.vglc import load_corpus

DATA = Path(__file__).resolve().parents[1] / "data" / "TheVGLC"
CASES = Path(__file__).resolve().parents[1] / "eval" / "cases"


@pytest.fixture(scope="session")
def corpus():
    if not DATA.exists():
        pytest.skip("corpus not fetched; run scripts/fetch_data.sh")
    return load_corpus(DATA)


@pytest.fixture(scope="session")
def cases():
    from dungeon_repair.corrupt import read_cases

    if not CASES.exists() or not any(CASES.glob("*.json")):
        pytest.skip("evaluation set not built; run dungeon-repair build-cases")
    return read_cases(CASES)


class ScriptedClient:
    """A model stand-in: replays a fixed list of replies, records what it was asked.

    Lets the agent loop, the tool dispatch, the rejection path and the trace
    format be tested without credentials or network.
    """

    def __init__(self, script):
        self.script = list(script)
        self.model = "scripted/test"
        self.usage = Usage()
        self.seen = []

    def complete(self, messages, tools=None, system=None):
        self.seen.append({"messages": list(messages), "tools": tools, "system": system})
        if not self.script:
            return ModelReply(text="done", tool_calls=[])
        text, calls = self.script.pop(0)
        tool_calls = [
            {"id": f"call_{i}", "name": name, "arguments": args}
            for i, (name, args) in enumerate(calls)
        ]
        self.usage.add(DEFAULT_MODEL, 100, 20)
        return ModelReply(
            text=text, tool_calls=tool_calls, input_tokens=100, output_tokens=20
        )


@pytest.fixture
def scripted():
    return ScriptedClient
