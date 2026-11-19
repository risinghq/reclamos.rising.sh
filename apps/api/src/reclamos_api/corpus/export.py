"""`reclamos dataset export`: write the corpus as JSONL files.

Every text field is the redacted text: resolutions come from `redacted_body`,
rule documents from their own `redacted_body`, passages from `chunks` and
`rule_passages`, which are built from redacted text. No PDFs, no embeddings
and no cards. The export refuses to write when a resolution that has a body,
or a rule document, has no redacted text at the current redactor version.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

from reclamos_api.config import Settings
from reclamos_api.corpus.redact import REDACTOR_VERSION
from reclamos_api.db import database_pool


class ExportError(Exception):
    pass


async def export_dataset(settings: Settings, directory: Path) -> str:
    async with (
        database_pool(
            settings.database_url, queue_schema=settings.queue_schema
        ) as pool,
        pool.acquire() as connection,
    ):
        missing_resolutions = await connection.fetchval(
            """
            SELECT count(*) FROM resolutions
            WHERE body IS NOT NULL AND body <> ''
              AND (redacted_body IS NULL OR redactor_version IS DISTINCT FROM $1)
            """,
            REDACTOR_VERSION,
        )
        missing_documents = await connection.fetchval(
            """
            SELECT count(*) FROM rule_documents
            WHERE redacted_body IS NULL OR redactor_version IS DISTINCT FROM $1
            """,
            REDACTOR_VERSION,
        )
        if missing_resolutions or missing_documents:
            raise ExportError(
                f"{missing_resolutions} resolutions and {missing_documents} rule "
                f"documents have no redacted text at redactor version "
                f"{REDACTOR_VERSION}; run `reclamos corpus crawl` and "
                "`reclamos rules sync` first"
            )
        missing_chunks = await connection.fetchval(
            """
            SELECT count(*) FROM resolutions r
            WHERE r.redacted_body IS NOT NULL AND r.chunked_at IS NULL
            """
        )
        if missing_chunks:
            raise ExportError(
                f"{missing_chunks} redacted resolutions have no chunks; run "
                "`reclamos corpus crawl` or `reclamos corpus reindex chunks` first"
            )
        resolutions = await connection.fetch(
            """
            SELECT id, page_url, expediente, published_on, summary,
                   pdf_url, pdf_sha256, pdf_bytes, page_count, ocr_pages,
                   text_method, number, resolved_on, operator, subject,
                   claim_type, appeal_kind, outcome, is_precedent, redacted_body
            FROM resolutions ORDER BY id
            """
        )
        passages = await connection.fetch(
            """
            SELECT resolution_id, ordinal, section, page_start, page_end,
                   char_start, char_end, text
            FROM chunks ORDER BY resolution_id, ordinal
            """
        )
        documents = await connection.fetch(
            """
            SELECT slug, title, kind, approved_by, text_date, pdf_url,
                   pdf_sha256, visitor_searchable, redacted_body
            FROM rule_documents ORDER BY slug
            """
        )
        rule_passages = await connection.fetch(
            """
            SELECT document_slug, ordinal, label, text_source, text_date,
                   pdf_url, text
            FROM rule_passages ORDER BY document_slug, ordinal
            """
        )
    directory.mkdir(parents=True, exist_ok=True)
    written = {
        "resolutions.jsonl": [_resolution(row) for row in resolutions],
        "passages.jsonl": [_mapping(row) for row in passages],
        "rule_documents.jsonl": [_document(row) for row in documents],
        "rule_passages.jsonl": [_mapping(row) for row in rule_passages],
    }
    lines: list[str] = []
    for name, records in written.items():
        path = directory / name
        path.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False) + "\n" for record in records
            ),
            encoding="utf-8",
        )
        lines.append(f"{path}: {len(records)} records")
    return "\n".join(lines)


def _resolution(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "page_url": row["page_url"],
        "expediente": row["expediente"],
        "published_on": _date(row["published_on"]),
        "summary": row["summary"],
        "pdf_url": row["pdf_url"],
        "pdf_sha256": row["pdf_sha256"],
        "pdf_bytes": row["pdf_bytes"],
        "page_count": row["page_count"],
        "ocr_pages": row["ocr_pages"],
        "text_method": row["text_method"],
        "number": row["number"],
        "resolved_on": _date(row["resolved_on"]),
        "operator": row["operator"],
        "subject": row["subject"],
        "claim_type": row["claim_type"],
        "appeal_kind": row["appeal_kind"],
        "outcome": row["outcome"],
        "is_precedent": row["is_precedent"],
        "text": row["redacted_body"],
    }


def _document(row: Any) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "title": row["title"],
        "kind": row["kind"],
        "approved_by": row["approved_by"],
        "text_date": _date(row["text_date"]),
        "pdf_url": row["pdf_url"],
        "pdf_sha256": row["pdf_sha256"],
        "visitor_searchable": row["visitor_searchable"],
        "text": row["redacted_body"],
    }


def _mapping(row: Any) -> dict[str, Any]:
    return {key: _date(value) for key, value in dict(row).items()}


def _date(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value
