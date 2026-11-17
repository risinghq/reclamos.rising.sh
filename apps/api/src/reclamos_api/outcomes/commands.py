import asyncio
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from reclamos_api.config import Settings
from reclamos_api.corpus.site import USER_AGENT
from reclamos_api.db import database_pool
from reclamos_api.outcomes import repository
from reclamos_api.outcomes.repository import Loaded
from reclamos_api.outcomes.source import (
    SOURCE_URL,
    FileKey,
    SourceError,
    file_key,
    read_zip,
)

SINCE = 2016


async def load(settings: Settings, zip_path: Path | None) -> str:
    if zip_path is not None:
        return await _load(settings, zip_path)
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "punku.zip"
        await download(path)
        return await _load(settings, path)


async def download(path: Path) -> None:
    try:
        async with (
            httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
            ) as client,
            client.stream("GET", SOURCE_URL) as response,
        ):
            response.raise_for_status()
            with path.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    file.write(chunk)
    except httpx.HTTPError as error:
        reason = ": ".join(filter(None, (type(error).__name__, str(error))))
        raise SourceError(
            f"could not download {SOURCE_URL} ({reason}); download it another way"
            " and pass --zip"
        ) from error


async def _load(settings: Settings, path: Path) -> str:
    books = await asyncio.to_thread(read_zip, path)
    async with (
        database_pool(
            settings.database_url, queue_schema=settings.queue_schema
        ) as pool,
        pool.acquire() as connection,
        connection.transaction(),
    ):
        loaded = await repository.load(connection, books)
        years = await repository.decisions_by_year(connection)
        sentidos = await repository.decisions_by_sentido(connection)
        match = await corpus_match(connection)
    return "\n".join(
        [
            f"source: {SOURCE_URL}, cut {books.cut_on.isoformat()}",
            *_summary(loaded),
            "decisions by year:",
            *(f"  {year} {count:,}" for year, count in years),
            "decisions by sentido:",
            *(f"  {sentido} {count:,}" for sentido, count in sentidos),
            *match,
        ]
    )


def _summary(loaded: Loaded) -> list[str]:
    return [
        f"decisions: {loaded.decisions:,} rows, {loaded.files:,} files",
        f"subjects: {loaded.subjects:,} file concepts, {loaded.stats:,} counts",
        f"concept labels not in the table: {len(loaded.unmapped)}",
        *(f"  {label} {count:,}" for label, count in loaded.unmapped.items()),
    ]


async def corpus_match(connection: Any) -> list[str]:
    resolutions = await repository.corpus_resolutions(connection)
    first, last = await repository.decision_window(connection)
    keys = {expediente: file_key(expediente) for expediente, _ in resolutions}
    kinds = await repository.kinds_filed(
        connection, [(key.year, key.number) for key in keys.values() if key]
    )
    recent = [
        (expediente, resolved_on, key)
        for expediente, resolved_on in resolutions
        if (key := keys[expediente]) is not None and key.year >= SINCE
    ]
    misses = [
        (expediente, reason)
        for expediente, resolved_on, key in recent
        if (
            reason := _miss(
                key, resolved_on, kinds.get((key.year, key.number), set()), first, last
            )
        )
        is not None
    ]
    unparsed = sum(key is None for key in keys.values())
    return [
        f"corpus: {len(recent) - len(misses)} of {len(recent)} expedientes"
        f" numbered {SINCE} or later match a file",
        f"  {unparsed} older expedientes name no ST-RA or ST-RQJ file",
        *(f"  {expediente}: {reason}" for expediente, reason in misses),
    ]


def _miss(
    key: FileKey, resolved_on: date | None, kinds: set[str], first: date, last: date
) -> str | None:
    if key.kind in kinds:
        return None
    if resolved_on is not None and resolved_on < first:
        return f"resolved {resolved_on}, before the first decision in 11.2 ({first})"
    if resolved_on is not None and resolved_on > last:
        return f"resolved {resolved_on}, after the last decision in 11.2 ({last})"
    if kinds:
        return f"11.2 holds this number only as {', '.join(sorted(kinds))}"
    return f"11.2 holds no {key.kind} file with this number"
