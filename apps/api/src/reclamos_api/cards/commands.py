"""The `reclamos cards` commands. Each one runs offline: cards are written and
judged ahead of time, so no visitor request calls a model."""

import asyncio
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import Any, cast

from reclamos_api.cards import repository
from reclamos_api.cards.card import (
    FIELDS,
    PROMPT_VERSION,
    Unreadable,
    redact_card,
    write_card,
)
from reclamos_api.cards.judge import JUDGE_VERSION, judge_card
from reclamos_api.config import Settings
from reclamos_api.corpus.redact import redactor_from_settings
from reclamos_api.db import database_pool
from reclamos_api.llm.client import LanguageModel, NotBilled, ProviderFailed
from reclamos_api.llm.quotes import normalize
from reclamos_api.llm.spend import Budget, Ledger, SpendRefused

DEFAULT_CONCURRENCY = 4


async def build(
    settings: Settings,
    model: LanguageModel,
    *,
    budget_usd: float,
    concurrency: int = DEFAULT_CONCURRENCY,
    limit: int | None = None,
) -> str:
    """Write a card for every resolution without a current one. Stops before
    the run would pass `budget_usd` or the daily cap."""
    budget = Budget(budget_usd)
    failed: list[str] = []
    written = 0
    redactor = redactor_from_settings(settings)
    async with database_pool(
        settings.database_url, queue_schema=settings.queue_schema
    ) as pool:
        ledger = Ledger(pool, daily_cap_usd=settings.daily_usd_cap)
        async with pool.acquire() as connection:
            sources = (await repository.stale_sources(connection))[:limit]

        async def one(source: repository.Source) -> None:
            nonlocal written
            try:
                card, usd = await write_card(
                    ledger, model, settings.card_model, source.body, budget=budget
                )
            except Unreadable as error:
                failed.append(f"{source.resolution_id}: {error}")
                return
            except ProviderFailed as error:
                failed.append(f"{source.resolution_id}: the provider failed: {error}")
                return
            redact_card(card, redactor.redact)
            async with pool.acquire() as connection:
                await repository.save_card(
                    connection, source, card, model=settings.card_model, usd=usd
                )
            written += 1

        stopped = await _run_all(sources, one, concurrency)
    lines = [f"cards written: {written} of {len(sources)} without a current card"]
    lines += [f"unreadable {line}" for line in failed]
    if stopped:
        lines.append(f"stopped: {stopped}")
    lines.append(f"spent US${budget.spent_usd:.4f} of US${budget_usd:.2f}")
    return "\n".join(lines)


async def judge(
    settings: Settings,
    model: LanguageModel,
    *,
    budget_usd: float,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> str:
    """Judge every current card that has no current verdict."""
    budget = Budget(budget_usd)
    unread: list[int] = []
    judged = 0
    async with database_pool(
        settings.database_url, queue_schema=settings.queue_schema
    ) as pool:
        ledger = Ledger(pool, daily_cap_usd=settings.daily_usd_cap)
        async with pool.acquire() as connection:
            cards = await repository.unjudged(connection)

        async def one(card: tuple[int, Any]) -> None:
            nonlocal judged
            resolution_id, fields = card
            try:
                verdict = await judge_card(
                    ledger, model, settings.judge_model, fields, budget=budget
                )
            except ProviderFailed:
                unread.append(resolution_id)
                return
            if verdict.unsupported is None:
                unread.append(resolution_id)
                return
            async with pool.acquire() as connection:
                await repository.save_verdict(
                    connection,
                    resolution_id,
                    verdict.unsupported,
                    judge_model=settings.judge_model,
                )
            judged += 1

        stopped = await _run_all(cards, one, concurrency)
    lines = [f"cards judged: {judged} of {len(cards)} without a verdict"]
    if unread:
        lines.append(f"verdict unreadable: {', '.join(map(str, unread))}")
    if stopped:
        lines.append(f"stopped: {stopped}")
    lines.append(f"spent US${budget.spent_usd:.4f} of US${budget_usd:.2f}")
    return "\n".join(lines)


async def redact(settings: Settings) -> str:
    """Redact every stored card the current redactor has not written. The card
    keeps `written_at` and its verdict: only the text changes."""
    redactor = redactor_from_settings(settings)
    updated = 0
    async with (
        database_pool(
            settings.database_url, queue_schema=settings.queue_schema
        ) as pool,
        pool.acquire() as connection,
    ):
        for row in await repository.unredacted(connection):
            fields = _redact_json(row["fields"], redactor.redact)
            readings = _redact_json(row["readings"], redactor.redact)
            rejected = _redact_json(row["rejected"], redactor.redact)
            await repository.apply_redaction(
                connection,
                row["resolution_id"],
                fields=fields,
                readings=readings,
                rejected=rejected,
            )
            updated += 1
    return f"cards redacted: {updated}"


def _redact_json(stored: Any, redact: Callable[[str], str]) -> str:
    """The JSON text with every string value redacted, structure unchanged."""
    data = json.loads(stored)

    def walk(value: Any) -> Any:
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, list):
            return [walk(item) for item in cast("list[Any]", value)]
        if isinstance(value, dict):
            return {
                key: walk(item) for key, item in cast("dict[str, Any]", value).items()
            }
        return value

    return json.dumps(walk(data))


async def _run_all[T](
    items: Sequence[T], work: Callable[[T], Awaitable[None]], concurrency: int
) -> str | None:
    """Run `work` on each item, `concurrency` at a time. The first call refused
    by the spend limits or by the provider stops new work; calls in flight
    finish. Returns the refusal.

    A provider refusal, such as its usage limit, would refuse every later call
    too, and the next run picks up where this one stopped."""
    pending = iter(items)
    stopped: str | None = None

    async def worker() -> None:
        nonlocal stopped
        for item in pending:
            if stopped is not None:
                return
            try:
                await work(item)
            except SpendRefused as refused:
                stopped = stopped or str(refused)
                return
            except NotBilled as refused:
                stopped = stopped or f"the provider refused: {refused}"
                return

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return stopped


async def report(settings: Settings) -> str:
    """What the cards hold, what the checks dropped, and where the model's
    reading and parse disagree."""
    async with (
        database_pool(
            settings.database_url, queue_schema=settings.queue_schema
        ) as pool,
        pool.acquire() as connection,
    ):
        rows = await repository.report_rows(connection)
    return format_report(rows)


def format_report(rows: Sequence[Any]) -> str:
    """Counts over the current cards and their current verdicts. A stale card
    is counted, not read: its prompt may have stored another shape."""
    current = [row for row in rows if row["prompt_version"] == PROMPT_VERSION]
    points: Counter[str] = Counter()
    dropped_points = dropped_readings = 0
    disagree: list[str] = []
    filled: list[str] = []
    judged = faithful = judged_points = 0
    unsupported: Counter[str] = Counter()
    for row in current:
        card_points = Counter(
            {
                name: len(field)
                for name, field in repository.card_fields(row["fields"]).items()
            }
        )
        points.update(card_points)
        for entry in json.loads(row["rejected"]):
            if "reading" in entry:
                dropped_readings += 1
            else:
                dropped_points += 1
        readings = json.loads(row["readings"])
        for name, parsed in (
            ("outcome", row["outcome"]),
            ("operator", row["operator"]),
            ("resolved_on", row["resolved_on"]),
        ):
            if name not in readings:
                continue
            read = readings[name]["value"]
            if parsed is None:
                filled.append(f"{row['resolution_id']} {name}: {read}")
            elif not _same(name, parsed, read):
                disagree.append(
                    f"{row['resolution_id']} {name}: parse {parsed}, card {read}"
                )
        if row["judge_version"] == JUDGE_VERSION:
            judged += 1
            judged_points += card_points.total()
            flagged = {
                (item["field"], item["point"])
                for item in json.loads(row["unsupported"])
            }
            faithful += not flagged
            unsupported.update(name for name, _ in flagged)
    served = judged_points - unsupported.total()
    lines = [
        f"cards: {len(rows)} ({len(current)} current),"
        f" US${sum(r['usd'] for r in rows):.4f}",
        "points: " + ", ".join(f"{name} {points[name]}" for name in FIELDS),
        f"dropped: {dropped_points} points, {dropped_readings} readings",
        f"judged: {judged}, faithful {faithful}"
        + (f" ({faithful / judged:.1%})" if judged else ""),
        "unsupported points by field: "
        + (
            ", ".join(f"{n} {unsupported[n]}" for n in FIELDS if unsupported[n])
            or "none"
        ),
        f"points served: {served} of {judged_points} judged"
        + (f" ({served / judged_points:.1%})" if judged_points else ""),
        f"disagreements with parse: {len(disagree)}",
        *(f"  {line}" for line in disagree),
        f"readings where parse has none: {len(filled)}",
        *(f"  {line}" for line in filled),
    ]
    return "\n".join(lines)


def _same(name: str, parsed: Any, read: str) -> bool:
    if name == "resolved_on":
        return isinstance(parsed, date) and parsed.isoformat() == read
    if name == "operator":
        return _letters(str(parsed)) == _letters(read)
    return parsed == read


def _letters(name: str) -> str:
    return re.sub(r"[^a-z]", "", normalize(name))
