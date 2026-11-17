from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from reclamos_api.outcomes.labels import (
    brand_of_company,
    concept_of,
    detail_key,
    detail_text,
    outcome_of,
)
from reclamos_api.outcomes.source import SOURCE_URL, Workbooks

MIN_FILES = 100

_DECISION_COLUMNS = (
    "year",
    "number",
    "kind",
    "resolved_on",
    "sentido",
    "outcome",
    "company",
    "brand",
)
_SUBJECT_COLUMNS = ("year", "number", "kind", "concept", "detail")


@dataclass(frozen=True, slots=True)
class Loaded:
    decisions: int
    files: int
    subjects: int
    stats: int
    unmapped: dict[str, int]


async def load(connection: Any, books: Workbooks) -> Loaded:
    decisions = [
        (
            d.file.year,
            d.file.number,
            d.file.kind,
            d.resolved_on,
            d.sentido,
            outcome_of(d.sentido),
            d.company,
            brand_of_company(d.company),
        )
        for d in books.decisions
    ]
    printed: dict[str, Counter[str]] = defaultdict(Counter)
    for subject in books.subjects:
        printed[detail_key(subject.subconcepto)][subject.subconcepto] += 1
    shown = {
        key: detail_text(forms.most_common(1)[0][0])
        for key, forms in printed.items()
        if key
    }
    unmapped: Counter[str] = Counter()
    subjects: set[tuple[int, int, str, str, str]] = set()
    for subject in books.subjects:
        concept = concept_of(subject.concepto)
        if concept is None:
            unmapped[subject.concepto] += 1
            concept = subject.concepto.lower()
        file = subject.file
        subjects.add(
            (
                file.year,
                file.number,
                file.kind,
                concept,
                shown.get(detail_key(subject.subconcepto), ""),
            )
        )
    async with connection.transaction():
        await connection.execute(
            "TRUNCATE outcome_source, outcome_decisions, outcome_subjects, outcome_stats"
        )
        await connection.copy_records_to_table(
            "outcome_decisions", records=decisions, columns=_DECISION_COLUMNS
        )
        await connection.copy_records_to_table(
            "outcome_subjects", records=sorted(subjects), columns=_SUBJECT_COLUMNS
        )
        await connection.execute(_FACTS)
        await connection.execute(_STATS, MIN_FILES)
        await connection.execute(
            "INSERT INTO outcome_source (url, cut_on) VALUES ($1, $2)",
            SOURCE_URL,
            books.cut_on,
        )
        files = await connection.fetchval(
            "SELECT count(*) FROM (SELECT DISTINCT year, number, kind"
            " FROM outcome_decisions)"
        )
        stats = await connection.fetchval("SELECT count(*) FROM outcome_stats")
    return Loaded(
        decisions=len(decisions),
        files=files,
        subjects=len(subjects),
        stats=stats,
        unmapped=dict(unmapped.most_common()),
    )


_FACTS = """
CREATE TEMP TABLE outcome_facts ON COMMIT DROP AS
WITH latest AS (
    SELECT DISTINCT ON (year, number, kind)
        year, number, kind, outcome, brand,
        extract(year FROM resolved_on)::int AS decided
    FROM outcome_decisions
    ORDER BY year, number, kind, resolved_on DESC
)
SELECT DISTINCT s.kind, s.concept, level.detail, s.year, s.number,
       l.outcome, l.brand, l.decided
FROM outcome_subjects s
JOIN latest l USING (year, number, kind)
CROSS JOIN LATERAL (VALUES (''), (s.detail)) AS level (detail)
"""

_STATS = """
INSERT INTO outcome_stats (kind, concept, detail, brand, files, fundado,
                           fundado_en_parte, infundado, improcedente, other,
                           first_year, last_year)
SELECT kind, concept, detail, coalesce(brand, ''), count(*),
       count(*) FILTER (WHERE outcome = 'fundado'),
       count(*) FILTER (WHERE outcome = 'fundado_en_parte'),
       count(*) FILTER (WHERE outcome = 'infundado'),
       count(*) FILTER (WHERE outcome = 'improcedente'),
       count(*) FILTER (WHERE outcome = 'other'),
       min(decided), max(decided)
FROM outcome_facts
GROUP BY GROUPING SETS ((kind, concept, detail), (kind, concept, detail, brand))
HAVING GROUPING(brand) = 1 OR (brand IS NOT NULL AND count(*) >= $1)
"""


async def decisions_by_year(connection: Any) -> list[tuple[int, int]]:
    rows = await connection.fetch(
        "SELECT extract(year FROM resolved_on)::int AS year, count(*) AS n"
        " FROM outcome_decisions GROUP BY 1 ORDER BY 1"
    )
    return [(row["year"], row["n"]) for row in rows]


async def decisions_by_sentido(connection: Any) -> list[tuple[str, int]]:
    rows = await connection.fetch(
        "SELECT sentido, count(*) AS n FROM outcome_decisions"
        " GROUP BY 1 ORDER BY 2 DESC, 1"
    )
    return [(row["sentido"], row["n"]) for row in rows]


async def kinds_filed(
    connection: Any, numbers: Sequence[tuple[int, int]]
) -> dict[tuple[int, int], set[str]]:
    rows = await connection.fetch(
        "SELECT DISTINCT year, number, kind FROM outcome_decisions"
        " JOIN unnest($1::int[], $2::int[]) AS w (year, number) USING (year, number)",
        [year for year, _ in numbers],
        [number for _, number in numbers],
    )
    found: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in rows:
        found[(row["year"], row["number"])].add(row["kind"])
    return found


async def decision_window(connection: Any) -> tuple[date, date]:
    row = await connection.fetchrow(
        "SELECT min(resolved_on) AS first, max(resolved_on) AS last"
        " FROM outcome_decisions"
    )
    return row["first"], row["last"]


async def corpus_resolutions(connection: Any) -> list[tuple[str, date | None]]:
    rows = await connection.fetch(
        "SELECT expediente, resolved_on FROM resolutions ORDER BY 1"
    )
    return [(row["expediente"], row["resolved_on"]) for row in rows]
