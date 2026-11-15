"""The `cards` table."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from reclamos_api.cards.card import PROMPT_VERSION, Card, Point, Points
from reclamos_api.cards.judge import JUDGE_VERSION


@dataclass(frozen=True, slots=True)
class Source:
    resolution_id: int
    body: str
    body_sha256: str


def body_sha256(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


async def stale_sources(connection: Any) -> list[Source]:
    """Resolutions with a body and no current card, smallest id first."""
    rows = await connection.fetch(
        """
        SELECT r.id, r.body, c.prompt_version, c.body_sha256
        FROM resolutions r LEFT JOIN cards c ON c.resolution_id = r.id
        WHERE r.body IS NOT NULL AND r.body <> ''
        ORDER BY r.id
        """
    )
    sources: list[Source] = []
    for row in rows:
        digest = body_sha256(row["body"])
        if row["prompt_version"] != PROMPT_VERSION or row["body_sha256"] != digest:
            sources.append(Source(row["id"], row["body"], digest))
    return sources


async def save_card(
    connection: Any, source: Source, card: Card, *, model: str, usd: float
) -> None:
    """Write the card, replacing an older one and its verdict."""
    await connection.execute(
        """
        INSERT INTO cards (resolution_id, prompt_version, body_sha256, model,
                           fields, readings, rejected, usd)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::float8)
        ON CONFLICT (resolution_id) DO UPDATE SET
            prompt_version = excluded.prompt_version,
            body_sha256 = excluded.body_sha256,
            model = excluded.model,
            fields = excluded.fields,
            readings = excluded.readings,
            rejected = excluded.rejected,
            usd = excluded.usd,
            written_at = now(),
            judge_model = NULL,
            judge_version = NULL,
            unsupported = NULL,
            judged_at = NULL
        """,
        source.resolution_id,
        PROMPT_VERSION,
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
    )


def card_fields(stored: str) -> dict[str, Points]:
    """The fields of a card as `save_card` stored them."""
    return {
        name: tuple(Point(point["text"], point["quote"]) for point in points)
        for name, points in json.loads(stored).items()
    }


async def unjudged(connection: Any) -> list[tuple[int, dict[str, Points]]]:
    """Current cards with at least one field and no current verdict, smallest
    id first."""
    rows = await connection.fetch(
        """
        SELECT resolution_id, fields FROM cards
        WHERE judge_version IS DISTINCT FROM $2
          AND fields <> '{}'::jsonb AND prompt_version = $1
        ORDER BY resolution_id
        """,
        PROMPT_VERSION,
        JUDGE_VERSION,
    )
    return [(row["resolution_id"], card_fields(row["fields"])) for row in rows]


async def save_verdict(
    connection: Any,
    resolution_id: int,
    unsupported: list[dict[str, Any]],
    *,
    judge_model: str,
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
        JUDGE_VERSION,
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
        FROM cards c JOIN resolutions r ON r.id = c.resolution_id
        WHERE c.resolution_id = ANY($1::bigint[])
          AND c.prompt_version = $2
          AND c.body_sha256 = encode(sha256(convert_to(r.body, 'UTF8')), 'hex')
          AND c.judge_version = $3
        """,
        resolution_ids,
        PROMPT_VERSION,
        JUDGE_VERSION,
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


async def report_rows(connection: Any) -> list[Any]:
    """Every card beside what parse read from the same resolution."""
    return await connection.fetch(
        """
        SELECT c.resolution_id, c.prompt_version, c.fields, c.readings, c.rejected,
               c.usd::float8 AS usd, c.judge_version, c.unsupported,
               r.outcome, r.operator, r.resolved_on
        FROM cards c JOIN resolutions r ON r.id = c.resolution_id
        ORDER BY c.resolution_id
        """
    )
