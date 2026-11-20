"""The `cards` table."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from reclamos_api.cards.card import PROMPT_VERSIONS, Card, Point, Points
from reclamos_api.cards.judge import JUDGE_VERSIONS
from reclamos_api.corpus.redact import REDACTOR_VERSION
from reclamos_api.corpus.sources import Sector


@dataclass(frozen=True, slots=True)
class Source:
    resolution_id: int
    sector: Sector
    body: str
    body_sha256: str


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


async def stale_sources(connection: Any, sector: Sector | None = None) -> list[Source]:
    """Resolutions with a body and no current card, smallest id first. A card
    is current under the prompt version of its resolution's sector."""
    rows = await connection.fetch(
        """
        SELECT r.id, r.sector, r.body, c.prompt_version, c.body_sha256
        FROM resolutions r LEFT JOIN cards c ON c.resolution_id = r.id
        WHERE r.body IS NOT NULL AND r.body <> ''
          AND ($1::text IS NULL OR r.sector = $1)
        ORDER BY r.id
        """,
        sector,
    )
    sources: list[Source] = []
    for row in rows:
        digest = body_sha256(row["body"])
        if (
            row["prompt_version"] != PROMPT_VERSIONS.get(row["sector"])
            or row["body_sha256"] != digest
        ):
            sources.append(Source(row["id"], row["sector"], row["body"], digest))
    return sources


async def save_card(
    connection: Any, source: Source, card: Card, *, model: str, usd: float
) -> None:
    """Write the card, replacing an older one and its verdict."""
    await connection.execute(
        """
        INSERT INTO cards (resolution_id, prompt_version, body_sha256, model,
                           fields, readings, rejected, usd, redactor_version)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::float8, $9)
        ON CONFLICT (resolution_id) DO UPDATE SET
            prompt_version = excluded.prompt_version,
            body_sha256 = excluded.body_sha256,
            model = excluded.model,
            fields = excluded.fields,
            readings = excluded.readings,
            rejected = excluded.rejected,
            usd = excluded.usd,
            redactor_version = excluded.redactor_version,
            written_at = now(),
            judge_model = NULL,
            judge_version = NULL,
            unsupported = NULL,
            judged_at = NULL
        """,
        source.resolution_id,
        PROMPT_VERSIONS[source.sector],
        source.body_sha256,
        model,
        json.dumps(
            {
                name: [asdict(point) for point in points]
                for name, points in card.fields.items()
            }
        ),
        json.dumps({name: asdict(r) for name, r in card.readings.items()}),
        json.dumps(card.rejected),
        usd,
        REDACTOR_VERSION,
    )


def card_fields(stored: str) -> dict[str, Points]:
    """The fields of a card as `save_card` stored them."""
    return {
        name: tuple(Point(point["text"], point["quote"]) for point in points)
        for name, points in json.loads(stored).items()
    }


async def unredacted(connection: Any) -> list[Any]:
    """Cards whose stored text was not redacted by the current redactor."""
    return await connection.fetch(
        """
        SELECT resolution_id, fields, readings, rejected FROM cards
        WHERE redactor_version IS DISTINCT FROM $1
        ORDER BY resolution_id
        """,
        REDACTOR_VERSION,
    )


async def apply_redaction(
    connection: Any,
    resolution_id: int,
    *,
    fields: str,
    readings: str,
    rejected: str,
) -> None:
    """Store the redacted card content. `written_at` and the judge columns do
    not change: the card is the same model output, redacted in place."""
    await connection.execute(
        """
        UPDATE cards
        SET fields = $2::jsonb, readings = $3::jsonb, rejected = $4::jsonb,
            redactor_version = $5
        WHERE resolution_id = $1
        """,
        resolution_id,
        fields,
        readings,
        rejected,
        REDACTOR_VERSION,
    )


async def unjudged(
    connection: Any, sector: Sector | None = None
) -> list[tuple[int, dict[str, Points], Sector]]:
    """Current cards with at least one field and no current verdict, smallest
    id first. A card is current under the prompt version of its resolution's
    sector, and its verdict under that sector's judge version."""
    rows = await connection.fetch(
        """
        SELECT c.resolution_id, c.fields, r.sector
        FROM cards c
        JOIN resolutions r ON r.id = c.resolution_id
        JOIN (VALUES ('telecom', $1, $2), ('energy', $3, $4))
             AS v(sector, prompt_version, judge_version)
          ON v.sector = r.sector
        WHERE c.prompt_version = v.prompt_version
          AND c.judge_version IS DISTINCT FROM v.judge_version
          AND c.fields <> '{}'::jsonb
          AND ($5::text IS NULL OR r.sector = $5)
        ORDER BY c.resolution_id
        """,
        PROMPT_VERSIONS["telecom"],
        JUDGE_VERSIONS["telecom"],
        PROMPT_VERSIONS["energy"],
        JUDGE_VERSIONS["energy"],
        sector,
    )
    return [
        (row["resolution_id"], card_fields(row["fields"]), row["sector"])
        for row in rows
    ]


async def save_verdict(
    connection: Any,
    resolution_id: int,
    unsupported: list[dict[str, Any]],
    *,
    judge_model: str,
    sector: Sector,
) -> None:
    await connection.execute(
        """
        UPDATE cards
        SET judge_model = $2, judge_version = $3, unsupported = $4::jsonb,
            judged_at = now()
        WHERE resolution_id = $1
        """,
        resolution_id,
        judge_model,
        JUDGE_VERSIONS[sector],
        json.dumps(unsupported),
    )


async def served_fields(
    connection: Any, resolution_ids: list[int]
) -> dict[int, dict[str, Points]]:
    """The points a visitor may read, by resolution. A card serves only while it
    and its verdict are current, and only the points the judge did not flag. A
    field with no point left is not served."""
    rows = await connection.fetch(
        """
        SELECT c.resolution_id, c.fields, c.unsupported
        FROM cards c
        JOIN resolutions r ON r.id = c.resolution_id
        JOIN (VALUES ('telecom', $2, $3), ('energy', $4, $5))
             AS v(sector, prompt_version, judge_version)
          ON v.sector = r.sector
        WHERE c.resolution_id = ANY($1::bigint[])
          AND c.prompt_version = v.prompt_version
          AND c.body_sha256 = encode(sha256(convert_to(r.body, 'UTF8')), 'hex')
          AND c.judge_version = v.judge_version
        """,
        resolution_ids,
        PROMPT_VERSIONS["telecom"],
        JUDGE_VERSIONS["telecom"],
        PROMPT_VERSIONS["energy"],
        JUDGE_VERSIONS["energy"],
    )
    served: dict[int, dict[str, Points]] = {}
    for row in rows:
        flagged = {
            (item["field"], item["point"]) for item in json.loads(row["unsupported"])
        }
        fields: dict[str, Points] = {}
        for name, points in card_fields(row["fields"]).items():
            kept = tuple(
                point
                for number, point in enumerate(points, start=1)
                if (name, number) not in flagged
            )
            if kept:
                fields[name] = kept
        if fields:
            served[row["resolution_id"]] = fields
    return served


async def report_rows(connection: Any, sector: Sector | None = None) -> list[Any]:
    """Every card beside what parse read from the same resolution."""
    return await connection.fetch(
        """
        SELECT c.resolution_id, c.prompt_version, c.fields, c.readings, c.rejected,
               c.usd::float8 AS usd, c.judge_version, c.unsupported,
               r.sector, r.outcome, r.operator, r.resolved_on
        FROM cards c JOIN resolutions r ON r.id = c.resolution_id
        WHERE ($1::text IS NULL OR r.sector = $1)
        ORDER BY c.resolution_id
        """,
        sector,
    )
