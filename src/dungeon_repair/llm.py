"""Model access through litellm, with token and cost accounting.

litellm is used rather than a provider SDK so the same code runs against
whatever key the person reproducing this happens to have -- the default is an
OpenAI model, and switching to Anthropic or anything else litellm supports is
one environment variable.

Prices come from litellm's own cost map, which ships with the pinned version of
the library and covers every provider it can call. That keeps one maintained
source of truth instead of a hand-copied table that silently goes stale.
``PRICE_OVERRIDES`` exists for a model litellm does not know yet; without an
entry there, and with nothing in litellm's map, cost is reported as unknown
rather than guessed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = "openai/gpt-5.6-luna"

#: Seconds before one request is abandoned. Generous next to the 5-15s a
#: reasoning model takes per call, but finite -- see Client.complete.
DEFAULT_TIMEOUT = 120.0
#: Retries per call, for the timeouts and transient 5xx a long run will hit.
DEFAULT_RETRIES = 2

#: USD per 1M tokens, (input, output). Only for models litellm's cost map is
#: missing -- normally empty. An entry here wins over litellm's map.
PRICE_OVERRIDES: dict[str, tuple[float, float]] = {}


def resolve_model(explicit: str | None = None) -> str:
    return explicit or os.environ.get("DUNGEON_REPAIR_MODEL") or DEFAULT_MODEL


#: Token count used to read a headline rate out of litellm's cost map. It is
#: deliberately small: several models price long context at a higher tier
#: (gpt-5.6-luna doubles its input rate above 272k tokens), so quoting a rate
#: from a million-token sample reports a tier this workload never reaches.
#: Actual spend is always computed from real token counts by `estimate_cost`.
_RATE_SAMPLE = 1_000


def price_of(model: str) -> tuple[float, float] | None:
    """Base rate in USD per 1M tokens, ``(input, output)``, or None.

    The base tier only. Models with long-context pricing charge more above
    their threshold; `estimate_cost` handles that, this does not.
    """
    bare = model.split("/")[-1]
    if bare in PRICE_OVERRIDES:
        return PRICE_OVERRIDES[bare]
    try:
        import litellm

        prompt, completion = litellm.cost_per_token(
            model=bare, prompt_tokens=_RATE_SAMPLE, completion_tokens=_RATE_SAMPLE
        )
        scale = 1_000_000 / _RATE_SAMPLE
        return (prompt * scale, completion * scale)
    except Exception:  # noqa: BLE001 - an unknown model is not an error here
        return None


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD for one call, or None when nothing knows this model's pricing."""
    bare = model.split("/")[-1]
    override = PRICE_OVERRIDES.get(bare)
    if override is not None:
        return (input_tokens * override[0] + output_tokens * override[1]) / 1_000_000
    try:
        import litellm

        prompt, completion = litellm.cost_per_token(
            model=bare, prompt_tokens=input_tokens, completion_tokens=output_tokens
        )
        return prompt + completion
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float | None = 0.0

    def add(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        spent = estimate_cost(model, input_tokens, output_tokens)
        if spent is None:
            self.cost_usd = None  # unknown pricing is reported, never guessed
        elif self.cost_usd is not None:
            self.cost_usd += spent

    def to_json(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


@dataclass
class ModelReply:
    text: str
    tool_calls: list[dict] = field(default_factory=list)
    raw_message: Any = None
    input_tokens: int = 0
    output_tokens: int = 0


class MissingCredentials(RuntimeError):
    pass


class Client:
    """Thin wrapper: one place that talks to a model, one place that counts cost."""

    def __init__(
        self,
        model: str | None = None,
        max_tokens: int = 4096,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ):
        self.model = resolve_model(model)
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.retries = retries
        self.usage = Usage()

    def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
    ) -> ModelReply:
        import litellm

        payload = list(messages)
        if system:
            payload = [{"role": "system", "content": system}] + payload

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "max_tokens": self.max_tokens,
            # Without an explicit timeout a request that never returns would
            # block its thread forever, and a pooled run could never finish --
            # results are only written once every case is done. Defensive: no
            # run has actually hung, but the failure mode costs a whole run.
            "timeout": self.timeout,
            "num_retries": self.retries,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # Deliberately no `temperature`: current frontier models on both
        # providers are reasoning models that reject sampling parameters, and
        # determinism here comes from the verified candidate set rather than
        # from decoding settings.
        api_base = os.environ.get("DUNGEON_REPAIR_API_BASE")
        if api_base:
            kwargs["api_base"] = api_base

        try:
            response = litellm.completion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
            if _looks_like_missing_key(exc):
                raise MissingCredentials(
                    f"no usable credentials for model {self.model!r}. Set the "
                    f"key for its provider ({_provider_hint(self.model)}) in "
                    "your environment or .env file."
                ) from exc
            raise

        choice = response.choices[0].message
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        self.usage.add(self.model, input_tokens, output_tokens)

        calls = []
        for call in getattr(choice, "tool_calls", None) or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"__unparsed__": call.function.arguments}
            calls.append(
                {"id": call.id, "name": call.function.name, "arguments": arguments}
            )

        return ModelReply(
            text=choice.content or "",
            tool_calls=calls,
            raw_message=choice,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _provider_hint(model: str) -> str:
    """The environment variable this model's provider most likely wants."""
    provider = model.split("/")[0] if "/" in model else ""
    bare = model.split("/")[-1]
    if provider == "anthropic" or bare.startswith("claude"):
        return "ANTHROPIC_API_KEY"
    if provider in ("openai", "") or bare.startswith("gpt"):
        return "OPENAI_API_KEY"
    return f"{provider.upper()}_API_KEY"


def _looks_like_missing_key(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in ("api key", "authentication", "auth_error", "unauthorized",
                       "credential", "no api_key")
    )


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader -- avoids a dependency for four lines of parsing."""
    from pathlib import Path

    file = Path(path)
    if not file.exists():
        return
    for line in file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def extract_json_object(text: str) -> dict | None:
    """Pull the first JSON object out of a model reply, fenced or bare."""
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        blocks = cleaned.split("```")
        for block in blocks[1::2]:
            body = block[4:] if block.lower().startswith("json") else block
            try:
                parsed = json.loads(body.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(cleaned[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
        start = cleaned.find("{", start + 1)
    return None
