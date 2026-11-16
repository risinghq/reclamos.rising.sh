import asyncio
import dataclasses
import json
from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from fakemodel import FakeModel
from reclamos_api.config import Settings
from reclamos_api.db import database_pool
from reclamos_api.llm.client import (
    MAX_PROMPT_CHARS,
    MODELS,
    AnthropicModel,
    Completion,
    MissingKey,
    NotBilled,
    OpenRouterModel,
    Prompt,
    ProviderFailed,
    UnpricedModel,
    model_for,
    worst_case_usd,
)
from reclamos_api.llm.quotes import is_quoted
from reclamos_api.llm.spend import Budget, Ledger, SpendRefused

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
# What FakeModel's default 10 input and 20 output tokens cost, at the published
# prices per million tokens: Haiku 5.5 $0.10 and $0.50, Sonnet 5.5 $2 and $10.
HAIKU_CALL_USD = 0.000011

PROMPT = Prompt(model=HAIKU, system="s", text="t" * 100, schema={}, max_tokens=100)
PASSAGE = "Se declara FUNDADO el recurso de apelación\npresentado por el usuario."


@pytest.mark.parametrize(
    ("quote", "quoted"),
    [
        pytest.param("FUNDADO el recurso de apelación", True, id="exact"),
        pytest.param(
            chr(0x201C) + "se declara fundado el recurso  de APELACION" + chr(0x201D),
            True,
            id="case-accents-spaces-and-quote-marks-differ",
        ),
        pytest.param("INFUNDADO el recurso de apelación", False, id="not-in-text"),
        pytest.param("el usuario.", False, id="too-short"),
    ],
)
def test_a_quote_counts_only_when_it_is_long_and_in_the_text(
    quote: str, quoted: bool
) -> None:
    assert is_quoted(quote, PASSAGE) == quoted


class FailingMessages:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, **_: Any) -> Any:
        raise self.error


class FailingClient:
    def __init__(self, error: Exception) -> None:
        self.messages = FailingMessages(error)


REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class RecordingMessages:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="..."),
                SimpleNamespace(type="text", text='{"supported": false}'),
            ],
            usage=SimpleNamespace(input_tokens=12, output_tokens=7),
            stop_reason="end_turn",
        )


class RecordingClient:
    def __init__(self) -> None:
        self.messages = RecordingMessages()


@pytest.mark.parametrize(
    ("model", "thinking"),
    [
        pytest.param(HAIKU, {"type": "disabled"}, id="haiku"),
        pytest.param(SONNET, {"type": "between_tools"}, id="sonnet"),
    ],
)
def test_every_request_turns_thinking_off_and_the_reply_is_its_text(
    model: str, thinking: dict[str, str]
) -> None:
    """Thinking tokens count against `max_tokens`. Left on, they spent the whole
    cap of a real answer before it wrote any text."""
    client = RecordingClient()
    prompt = dataclasses.replace(PROMPT, model=model)

    completion = asyncio.run(AnthropicModel(client=client).complete(prompt))

    assert client.messages.requests[0]["thinking"] == thinking
    assert client.messages.requests[0]["max_tokens"] == prompt.max_tokens
    assert completion.text == '{"supported": false}'
    assert (completion.input_tokens, completion.output_tokens) == (12, 7)


def test_only_an_error_status_from_the_api_counts_as_not_billed() -> None:
    """A status error is a refused request. A timeout may come after the model
    ran, so it must reach the ledger as it is and keep the reserved cost."""
    overloaded = anthropic.APIStatusError(
        "overloaded", response=httpx2.Response(529, request=REQUEST), body=None
    )
    with pytest.raises(NotBilled):
        asyncio.run(AnthropicModel(client=FailingClient(overloaded)).complete(PROMPT))
    with pytest.raises(anthropic.APITimeoutError):
        asyncio.run(
            AnthropicModel(
                client=FailingClient(anthropic.APITimeoutError(REQUEST))
            ).complete(PROMPT)
        )


FLASH = "deepseek/deepseek-v4-flash"


def openrouter(
    reply: httpx.Response, requests: list[httpx.Request] | None = None
) -> OpenRouterModel:
    def handle(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return reply

    return OpenRouterModel("key", transport=httpx.MockTransport(handle))


def choice(finish_reason: str) -> dict[str, Any]:
    return {
        "choices": [
            {"message": {"content": '{"a": 1}'}, "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "cost": 0.0004},
    }


def test_an_openrouter_request_caps_the_price_and_requires_the_schema() -> None:
    """`max_price` keeps a dearer endpoint from serving, so the worst case
    priced from MODELS holds. Without `require_parameters` an endpoint that
    ignores `response_format` may serve."""
    requests: list[httpx.Request] = []
    prompt = dataclasses.replace(PROMPT, model=FLASH, schema={"type": "object"})

    completion = asyncio.run(
        openrouter(httpx.Response(200, json=choice("stop")), requests).complete(prompt)
    )

    sent = json.loads(requests[0].content)
    assert requests[0].headers["authorization"] == "Bearer key"
    assert sent["max_tokens"] == prompt.max_tokens
    assert sent["reasoning"] == {"enabled": False}
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert sent["provider"]["require_parameters"] is True
    price = MODELS[FLASH].price
    assert sent["provider"]["max_price"] == {
        "prompt": price.input,
        "completion": price.output,
    }
    assert completion == Completion('{"a": 1}', 12, 7, "stop", usd=0.0004)


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        pytest.param(
            httpx.Response(200, json=choice("length")), "max_tokens", id="cut-reply"
        ),
        pytest.param(
            httpx.Response(200, json=choice("content_filter")),
            "refusal",
            id="filtered-reply",
        ),
        pytest.param(
            httpx.Response(402, json={"error": {"message": "no credits"}}),
            NotBilled,
            id="error-status",
        ),
        pytest.param(
            httpx.Response(200, json={"error": {"code": 502, "message": "down"}}),
            ProviderFailed,
            id="failed-mid-generation",
        ),
        pytest.param(
            httpx.Response(200, json={"choices": []}), ProviderFailed, id="no-choices"
        ),
    ],
)
def test_openrouter_replies_map_to_the_names_the_callers_check(
    reply: httpx.Response, outcome: str | type[Exception]
) -> None:
    """Only an error status is refused before the model ran. A 200 carrying an
    error may be billed, so it must not raise NotBilled."""
    prompt = dataclasses.replace(PROMPT, model=FLASH)
    if isinstance(outcome, str):
        completion = asyncio.run(openrouter(reply).complete(prompt))
        assert completion.stop_reason == outcome
    else:
        with pytest.raises(outcome):
            asyncio.run(openrouter(reply).complete(prompt))


@pytest.mark.parametrize(
    ("model", "key"),
    [
        pytest.param(SONNET, "ANTHROPIC_API_KEY", id="anthropic"),
        pytest.param(FLASH, "OPENROUTER_API_KEY", id="openrouter"),
    ],
)
def test_a_model_needs_its_own_provider_key(model: str, key: str) -> None:
    settings = Settings(
        database_url="postgresql://unused",
        anthropic_api_key="a" if key != "ANTHROPIC_API_KEY" else None,
        openrouter_api_key="o" if key != "OPENROUTER_API_KEY" else None,
    )
    with pytest.raises(MissingKey, match=key):
        model_for(settings, model)


def run_with_pool(url: str, work: Callable[[Any], Any]) -> Any:
    async def run() -> Any:
        async with database_pool(url, queue_schema="task_queue") as pool:
            return await work(pool)

    return asyncio.run(run())


async def llm_calls(pool: Any) -> list[Any]:
    async with pool.acquire() as connection:
        return await connection.fetch("SELECT * FROM llm_calls ORDER BY id")


@pytest.mark.integration
def test_the_daily_cap_counts_billed_failed_and_unbilled_calls_of_the_lima_day(
    database_url: str,
) -> None:
    worst = worst_case_usd(PROMPT)

    async def work(pool: Any) -> None:
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO llm_calls (started_at, purpose, model, reserved_usd, usd)
                VALUES (
                    date_trunc('day', now() AT TIME ZONE 'America/Lima')
                        AT TIME ZONE 'America/Lima' - interval '1 second',
                    'card', $1, 50, 50
                )
                """,
                HAIKU,
            )
        ledger = Ledger(pool, daily_cap_usd=1.5 * worst)
        budget = Budget(limit_usd=1.0)
        assert await ledger.spent_today() == 0, "yesterday in Lima is not today"

        model = FakeModel(lambda _: "{}")
        metered = await ledger.complete(model, PROMPT, purpose="card", budget=budget)
        assert metered.usd == pytest.approx(HAIKU_CALL_USD)
        assert await ledger.spent_today() == pytest.approx(HAIKU_CALL_USD)

        model.error = NotBilled("529: overloaded")
        with pytest.raises(NotBilled):
            await ledger.complete(model, PROMPT, purpose="card", budget=budget)
        assert await ledger.spent_today() == pytest.approx(HAIKU_CALL_USD)

        model.error = TimeoutError()
        with pytest.raises(TimeoutError):
            await ledger.complete(model, PROMPT, purpose="judge", budget=budget)
        assert await ledger.spent_today() == pytest.approx(HAIKU_CALL_USD + worst)
        assert budget.spent_usd == pytest.approx(HAIKU_CALL_USD + worst)

        model.error = None
        with pytest.raises(SpendRefused, match="daily cap"):
            await ledger.complete(model, PROMPT, purpose="card", budget=budget)
        assert len(model.prompts) == 3, "a refused call never reaches the model"

        rows = (await llm_calls(pool))[1:]
        assert [r["purpose"] for r in rows] == ["card", "card", "judge"]
        assert all(r["finished_at"] is not None for r in rows)
        assert [r["input_tokens"] for r in rows] == [10, None, None]
        assert [float(r["usd"]) for r in rows] == pytest.approx(
            [HAIKU_CALL_USD, 0.0, worst]
        )
        assert [float(r["reserved_usd"]) for r in rows] == pytest.approx([worst] * 3)
        assert rows[0]["usd"] == Decimal(repr(HAIKU_CALL_USD)), (
            "an amount is stored as the float's shortest decimal"
        )
        assert rows[0]["reserved_usd"] == Decimal(repr(worst))
        assert rows[0]["error"] is None
        assert "overloaded" in rows[1]["error"]

    run_with_pool(database_url, work)


@pytest.mark.integration
def test_the_ledger_records_the_charge_a_provider_reports(database_url: str) -> None:
    """OpenRouter reports what the serving endpoint charged, which can be below
    the price in MODELS."""
    reported = HAIKU_CALL_USD / 4

    async def work(pool: Any) -> None:
        ledger = Ledger(pool, daily_cap_usd=1.0)
        budget = Budget(limit_usd=1.0)
        model = FakeModel(lambda _: "{}", usd=reported)
        metered = await ledger.complete(model, PROMPT, purpose="card", budget=budget)
        assert metered.usd == pytest.approx(reported)
        assert budget.spent_usd == pytest.approx(reported)
        assert await ledger.spent_today() == pytest.approx(reported)

    run_with_pool(database_url, work)


@pytest.mark.integration
@pytest.mark.parametrize("limit", ["daily cap", "run"])
def test_a_call_in_flight_counts_against_the_daily_cap_and_the_run_budget(
    database_url: str, limit: str
) -> None:
    room = 1.5 * worst_case_usd(PROMPT)

    async def work(pool: Any) -> None:
        ledger = Ledger(pool, daily_cap_usd=room if limit == "daily cap" else 100.0)
        budget = Budget(limit_usd=room if limit == "run" else 100.0)
        slow = FakeModel(lambda _: "{}", gate=asyncio.Event())
        first = asyncio.create_task(
            ledger.complete(slow, PROMPT, purpose="card", budget=budget)
        )
        await slow.started.wait()

        second = FakeModel(lambda _: "{}")
        with pytest.raises(SpendRefused, match=limit):
            await ledger.complete(second, PROMPT, purpose="card", budget=budget)
        assert second.prompts == []

        assert slow.gate is not None
        slow.gate.set()
        await first
        assert await ledger.spent_today() == pytest.approx(HAIKU_CALL_USD)
        assert budget.spent_usd == pytest.approx(HAIKU_CALL_USD)

    run_with_pool(database_url, work)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("prompt", "budget", "error"),
    [
        pytest.param(
            Prompt(HAIKU, "s", "t" * MAX_PROMPT_CHARS, {}, 100),
            None,
            SpendRefused,
            id="prompt-too-long",
        ),
        pytest.param(
            PROMPT, Budget(limit_usd=0.00001), SpendRefused, id="over-the-run-budget"
        ),
        pytest.param(
            Prompt("claude-unpriced", "s", "t", {}, 100),
            None,
            UnpricedModel,
            id="no-known-price",
        ),
    ],
)
def test_a_call_that_could_pass_a_limit_is_never_made_or_logged(
    database_url: str, prompt: Prompt, budget: Budget | None, error: type[Exception]
) -> None:
    async def work(pool: Any) -> None:
        model = FakeModel(lambda _: "{}")
        with pytest.raises(error):
            await Ledger(pool, daily_cap_usd=100.0).complete(
                model, prompt, purpose="card", budget=budget
            )
        assert model.prompts == []
        assert await llm_calls(pool) == []

    run_with_pool(database_url, work)
