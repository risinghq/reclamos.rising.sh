"""Calls to a hosted language model, and what each one costs."""

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import httpx
from reclamos_api.config import Settings


@dataclass(frozen=True, slots=True)
class Prompt:
    """One request. `schema` is the JSON schema the reply must follow."""

    model: str
    system: str
    text: str
    schema: dict[str, Any]
    max_tokens: int
    # A timeout can fire after the model ran, so the call stays billed. Set it
    # long enough for `max_tokens` of output.
    timeout_s: float = 60.0


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    # "max_tokens" means the reply was cut, so its JSON is incomplete.
    stop_reason: str | None
    # What the provider reports it charged. None means the ledger prices the
    # tokens from MODELS.
    usd: float | None = None

    def parsed(self) -> dict[str, Any] | None:
        """The reply as a JSON object, or None when it is not one."""
        try:
            value: Any = json.loads(self.text)
        except json.JSONDecodeError:
            return None
        return cast("dict[str, Any]", value) if isinstance(value, dict) else None


class NotBilled(Exception):
    """A model error raised before any token was billed, such as an HTTP error
    status. Any other error leaves the reserved cost counted."""


class ProviderFailed(Exception):
    """The provider accepted the request and failed while the model ran, so
    the call may be billed."""


class LanguageModel(Protocol):
    async def complete(self, prompt: Prompt) -> Completion: ...


@dataclass(frozen=True, slots=True)
class Price:
    """US dollars per million tokens."""

    input: float
    output: float

    def usd(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input + output_tokens * self.output) / 1_000_000


Provider = Literal["anthropic", "openrouter"]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: Provider
    # For OpenRouter, the highest price of any endpoint the request accepts:
    # it is sent as `provider.max_price`, so no endpoint above it serves the
    # call and the worst case computed from it stays an upper bound.
    price: Price
    # The setting that turns thinking off: Anthropic's `thinking`, OpenRouter's
    # `reasoning`. Without it the model may think, and its thinking tokens
    # count against `max_tokens`, so a short cap can end the reply before any
    # text is written. Haiku 5.5 takes "disabled"; Sonnet 5.5 rejects it and
    # takes "between_tools".
    # https://platform.claude.com/docs/en/api/errors, read 2026-11-14.
    thinking_off: dict[str, Any]


_OPENROUTER_NO_REASONING = {"enabled": False}

# https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-14.
# Haiku 5.5 doubles in price above 100,000 prompt tokens; MAX_PROMPT_CHARS keeps
# every prompt far below that. OpenRouter prices are the dearest endpoint that
# supports structured outputs below a long-context tier, from
# https://openrouter.ai/api/v1/models/<id>/endpoints, read 2026-11-16. A model
# missing here cannot be called, because its cost could not be capped.
MODELS = {
    "claude-haiku-5-5": ModelSpec(
        provider="anthropic",
        price=Price(input=0.10, output=0.50),
        thinking_off={"type": "disabled"},
    ),
    "claude-sonnet-5-5": ModelSpec(
        provider="anthropic",
        price=Price(input=2.00, output=10.00),
        thinking_off={"type": "between_tools"},
    ),
    "deepseek/deepseek-v4-flash": ModelSpec(
        provider="openrouter",
        price=Price(input=0.14, output=0.28),
        thinking_off=_OPENROUTER_NO_REASONING,
    ),
    "openai/gpt-6-luna": ModelSpec(
        provider="openrouter",
        price=Price(input=0.11, output=0.55),
        thinking_off=_OPENROUTER_NO_REASONING,
    ),
    "google/gemini-3.5-flash-lite": ModelSpec(
        provider="openrouter",
        price=Price(input=0.30, output=2.50),
        thinking_off=_OPENROUTER_NO_REASONING,
    ),
    # Free variants: a zero `max_price` keeps any paid endpoint from serving
    # them. OpenRouter allows 50 free requests a day, 1,000 once an account
    # has bought US$10 of credits, and their providers may log prompts.
    # https://openrouter.ai/docs/api/reference/limits, read 2026-11-16.
    "nvidia/nemotron-3.5-super-vl:free": ModelSpec(
        provider="openrouter",
        price=Price(input=0.0, output=0.0),
        thinking_off=_OPENROUTER_NO_REASONING,
    ),
    "inclusionai/ling-3.2-flash:free": ModelSpec(
        provider="openrouter",
        price=Price(input=0.0, output=0.0),
        thinking_off=_OPENROUTER_NO_REASONING,
    ),
}

MAX_PROMPT_CHARS = 40_000

# Spanish runs near four characters a token. Two is the bound used before a
# call, so the reserved cost is never below what the call is billed.
CHARS_PER_TOKEN_BOUND = 2


class UnpricedModel(Exception):
    pass


class MissingKey(Exception):
    pass


def spec_of(model: str) -> ModelSpec:
    try:
        return MODELS[model]
    except KeyError:
        raise UnpricedModel(
            f"no price is known for {model!r}; known: {', '.join(MODELS)}"
        ) from None


def price_of(model: str) -> Price:
    return spec_of(model).price


def worst_case_usd(prompt: Prompt) -> float:
    """The most `prompt` can cost: every character a token, every output token
    used."""
    characters = len(prompt.system) + len(prompt.text) + len(json.dumps(prompt.schema))
    return price_of(prompt.model).usd(
        characters // CHARS_PER_TOKEN_BOUND + 1, prompt.max_tokens
    )


def model_for(settings: Settings, model: str) -> LanguageModel:
    """The client of the provider that serves `model`."""
    provider = spec_of(model).provider
    if provider == "anthropic":
        if settings.anthropic_api_key is None:
            raise MissingKey(f"set ANTHROPIC_API_KEY to call {model}")
        return AnthropicModel(settings.anthropic_api_key)
    if settings.openrouter_api_key is None:
        raise MissingKey(f"set OPENROUTER_API_KEY to call {model}")
    return OpenRouterModel(settings.openrouter_api_key)


class AnthropicModel:
    """The Anthropic Messages API."""

    def __init__(self, api_key: str | None = None, *, client: Any = None) -> None:
        if client is None:
            from anthropic import AsyncAnthropic

            # Retries are left to the caller: each retry is billed again.
            client = AsyncAnthropic(api_key=api_key, max_retries=0)
        self._client = client

    async def complete(self, prompt: Prompt) -> Completion:
        from anthropic import APIStatusError

        try:
            message = await self._client.messages.create(
                model=prompt.model,
                max_tokens=prompt.max_tokens,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.text}],
                thinking=spec_of(prompt.model).thinking_off,
                output_config={
                    "format": {"type": "json_schema", "schema": prompt.schema}
                },
                timeout=prompt.timeout_s,
            )
        except APIStatusError as error:
            raise NotBilled(f"{error.status_code}: {error.message}") from error
        text = "".join(block.text for block in message.content if block.type == "text")
        return Completion(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason,
        )


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter's `finish_reason` in the names the callers check.
_STOP_REASONS = {"length": "max_tokens", "content_filter": "refusal"}


class OpenRouterModel:
    """OpenRouter's Chat Completions API.

    https://openrouter.ai/docs/api_reference/errors-and-debugging, read
    2026-11-16: an error status means the request was refused before the model
    ran. A model that fails after it started answers 200 with an `error` body.
    """

    def __init__(
        self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._api_key = api_key
        self._transport = transport

    async def complete(self, prompt: Prompt) -> Completion:
        spec = spec_of(prompt.model)
        request = {
            "model": prompt.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.text},
            ],
            "max_tokens": prompt.max_tokens,
            "reasoning": spec.thinking_off,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reply",
                    "strict": True,
                    "schema": prompt.schema,
                },
            },
            "provider": {
                # Without it an endpoint that ignores `response_format` may serve.
                "require_parameters": True,
                "max_price": {
                    "prompt": spec.price.input,
                    "completion": spec.price.output,
                },
            },
        }
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.post(
                OPENROUTER_URL,
                json=request,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=prompt.timeout_s,
            )
        if response.status_code >= 400:
            raise NotBilled(f"{response.status_code}: {response.text[:300]}")
        body: dict[str, Any] = response.json()
        if "error" in body or not body.get("choices"):
            raise ProviderFailed(json.dumps(body.get("error", body))[:300])
        choice: dict[str, Any] = body["choices"][0]
        usage: dict[str, Any] = body.get("usage") or {}
        cost: float | None = usage.get("cost")
        finish: str | None = choice.get("finish_reason")
        return Completion(
            text=choice["message"].get("content") or "",
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            stop_reason=_STOP_REASONS.get(finish, finish) if finish else None,
            usd=float(cost) if cost is not None else None,
        )
