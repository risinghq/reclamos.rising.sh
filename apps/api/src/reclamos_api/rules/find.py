from dataclasses import dataclass
from datetime import date
from typing import Any

from reclamos_api.corpus.repository import vector_literal
from reclamos_api.retrieval.embedder import Embedder
from reclamos_api.retrieval.search import require_index_model

MAX_RULES = 3
DEFAULT_MIN_TEXT_RANK = 0.05


@dataclass(frozen=True, slots=True)
class Rule:
    title: str
    kind: str
    label: str
    approved_by: str
    text_date: date
    pdf_url: str
    text: str
    similarity: float


async def find_rules(
    pool: Any,
    embedder: Embedder,
    *,
    query: str,
    min_similarity: float,
    min_text_rank: float = DEFAULT_MIN_TEXT_RANK,
    limit: int = MAX_RULES,
    sector: str | None = None,
) -> list[Rule]:
    vector = await embedder.embed_query(query)
    async with pool.acquire() as connection:
        await require_index_model(connection, embedder.model)
        rows = await connection.fetch(
            """
            WITH q AS (
                SELECT replace(
                    plainto_tsquery('spanish_unaccent', $2)::text, ' & ', ' | '
                )::tsquery AS query
            )
            SELECT d.title, d.kind, p.label, p.text_source, p.text_date, p.pdf_url,
                   p.text, 1 - (p.embedding <=> $1::vector) AS similarity
            FROM rule_passages p
            JOIN rule_documents d ON d.slug = p.document_slug
            CROSS JOIN q
            WHERE p.embedding IS NOT NULL
              AND d.visitor_searchable
              AND p.search @@ q.query
              AND ts_rank(p.search, q.query) >= $3
              AND ($5::text IS NULL OR d.sector = $5)
            ORDER BY p.embedding <=> $1::vector, p.document_slug, p.ordinal
            LIMIT $4
            """,
            vector_literal(vector),
            query,
            min_text_rank,
            limit,
            sector,
        )
    return [
        Rule(
            title=row["title"],
            kind=row["kind"],
            label=row["label"],
            approved_by=row["text_source"],
            text_date=row["text_date"],
            pdf_url=row["pdf_url"],
            text=row["text"],
            similarity=row["similarity"],
        )
        for row in rows
        if row["similarity"] >= min_similarity
    ]
