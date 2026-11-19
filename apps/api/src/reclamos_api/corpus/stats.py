from dataclasses import dataclass
from typing import Any

from reclamos_api.corpus.redact import LABELS, REDACTOR_VERSION
from reclamos_api.corpus.sources import SECTORS


@dataclass(frozen=True, slots=True)
class SectorStats:
    sector: str
    found: int
    skipped: dict[str, int]
    downloaded: int
    extracted: int
    extraction_methods: dict[str, int]
    redacted: int
    parsed: int
    chunked: int
    chunks: int
    embedded: int
    failures: dict[tuple[str, str], int]
    claim_types: dict[str, int]
    outcomes: dict[str, int]

    @property
    def failed(self) -> int:
        return sum(self.failures.values())


@dataclass(frozen=True, slots=True)
class CorpusStats:
    sectors: dict[str, SectorStats]
    redaction_labels: dict[str, int]
    failed_jobs: dict[str, int]
    listing_failures: dict[str, int]


async def collect_stats(pool: Any, *, queue_schema: str) -> CorpusStats:
    async with pool.acquire() as connection:
        totals = await connection.fetch(
            """
            SELECT sector,
                   count(*) AS found,
                   count(skipped_reason) FILTER (WHERE skipped_reason IS NOT NULL) AS skipped,
                   count(downloaded_at) AS downloaded,
                   count(extracted_at) AS extracted,
                   count(redacted_at) FILTER (
                       WHERE redactor_version = $1
                   ) AS redacted,
                   count(parsed_at) AS parsed,
                   count(chunked_at) AS chunked,
                   count(embedded_at) AS embedded
            FROM resolutions GROUP BY sector
            """,
            REDACTOR_VERSION,
        )
        skipped = await connection.fetch(
            """
            SELECT sector, skipped_reason, count(*) FROM resolutions
            WHERE skipped_reason IS NOT NULL GROUP BY 1, 2
            """
        )
        label_rows = await connection.fetch(
            "SELECT label, sum(n) AS n FROM ("
            + " UNION ALL ".join(
                f"SELECT '{name}' AS label, regexp_count(redacted_body, '{_pattern(label)}') AS n "
                "FROM resolutions WHERE redacted_body IS NOT NULL"
                for name, label in LABELS.items()
            )
            + ") counts GROUP BY label"
        )
        chunks = await connection.fetch(
            """
            SELECT r.sector, count(*) FROM chunks c
            JOIN resolutions r ON r.id = c.resolution_id GROUP BY 1
            """
        )
        methods = await connection.fetch(
            """
            SELECT sector, text_method, count(*) FROM resolutions
            WHERE text_method IS NOT NULL GROUP BY 1, 2
            """
        )
        failures = await connection.fetch(
            """
            SELECT sector, failure_stage, failure_reason, count(*) FROM resolutions
            WHERE failure_reason IS NOT NULL GROUP BY 1, 2, 3
            """
        )
        claim_types = await connection.fetch(
            """
            SELECT sector, claim_type, count(*) FROM resolutions
            WHERE parsed_at IS NOT NULL GROUP BY 1, 2
            """
        )
        outcomes = await connection.fetch(
            """
            SELECT sector, outcome, count(*) FROM resolutions
            WHERE parsed_at IS NOT NULL GROUP BY 1, 2
            """
        )
        # The queue schema name is validated by rqueue before it is installed.
        failed_jobs = await connection.fetch(
            f"SELECT task, count(*) FROM {queue_schema}.jobs "
            "WHERE state = 'failed' AND task LIKE 'corpus.%' GROUP BY 1"
        )
        listing_failures = await connection.fetch(
            "SELECT reason, count(*) FROM listing_failures GROUP BY 1"
        )

    sectors: dict[str, SectorStats] = {}
    totals_by = {row[0]: row for row in totals}
    chunk_counts = {row[0]: row[1] for row in chunks}
    for sector in SECTORS:
        row = totals_by.get(sector, {})
        sectors[sector] = SectorStats(
            sector=sector,
            found=row.get("found", 0),
            skipped={r[1]: r[2] for r in skipped if r[0] == sector},
            downloaded=row.get("downloaded", 0),
            extracted=row.get("extracted", 0),
            extraction_methods={r[1]: r[2] for r in methods if r[0] == sector},
            redacted=row.get("redacted", 0),
            parsed=row.get("parsed", 0),
            chunked=row.get("chunked", 0),
            chunks=chunk_counts.get(sector, 0),
            embedded=row.get("embedded", 0),
            failures={(r[1], r[2]): r[3] for r in failures if r[0] == sector},
            claim_types={r[1]: r[2] for r in claim_types if r[0] == sector},
            outcomes={r[1]: r[2] for r in outcomes if r[0] == sector},
        )
    return CorpusStats(
        sectors=sectors,
        redaction_labels={row["label"]: row["n"] for row in label_rows},
        failed_jobs={row[0]: row[1] for row in failed_jobs},
        listing_failures={row[0]: row[1] for row in listing_failures},
    )


def format_stats(stats: CorpusStats) -> str:
    lines: list[str] = []
    for sector in SECTORS:
        part = stats.sectors.get(sector)
        if part is None:
            continue
        lines.append(f"sector: {sector}")
        lines.append(f"  found                 {part.found}")
        if part.skipped:
            lines.append(f"  skipped               {sum(part.skipped.values())}")
            lines.extend("  " + line for line in _counts(part.skipped))
        lines.extend(
            [
                f"  downloaded            {part.downloaded}",
                f"  extracted             {part.extracted}"
                + _breakdown(part.extraction_methods),
                f"  redacted              {part.redacted}",
                f"  parsed                {part.parsed}",
                f"  chunked               {part.chunked}  ({part.chunks} chunks)",
                f"  embedded              {part.embedded}",
                f"  failed                {part.failed}",
            ]
        )
        for (stage, reason), count in sorted(part.failures.items()):
            lines.append(f"    {stage}: {reason}".ljust(26) + str(count))
        lines.append("  claim types")
        lines.extend("  " + line for line in _counts(part.claim_types))
        lines.append("  outcomes")
        lines.extend("  " + line for line in _counts(part.outcomes))
    if stats.redaction_labels:
        lines.append("redactions")
        lines.extend(_counts({LABELS[k]: v for k, v in stats.redaction_labels.items()}))
    if stats.listing_failures:
        lines.append("listing windows that could not be read")
        lines.extend(_counts(stats.listing_failures))
    if stats.failed_jobs:
        lines.append("queue jobs that exhausted their attempts")
        lines.extend(_counts(stats.failed_jobs))
    return "\n".join(lines)


def _pattern(label: str) -> str:
    return "\\" + label[0] + label[1:-1] + "\\" + label[-1]


def _breakdown(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return (
        "  ("
        + ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
        + ")"
    )


def _counts(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["  none"]
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"  {name}".ljust(26) + str(count) for name, count in ordered]
