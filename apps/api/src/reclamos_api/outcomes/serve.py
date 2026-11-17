from collections.abc import Iterable
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel
from reclamos_api.outcomes.labels import OUTCOME_KEYS
from reclamos_api.outcomes.repository import MIN_FILES
from reclamos_api.outcomes.source import FileKey, file_key


class OutcomeCounts(BaseModel):
    files: int
    first_year: int
    last_year: int
    outcomes: dict[str, int]


class BrandCounts(OutcomeCounts):
    brand: str


class ConceptStatistics(BaseModel):
    concept: str
    detail: str | None
    counts: OutcomeCounts
    brand: BrandCounts | None


class Statistics(BaseModel):
    file_type: Literal["RA", "RQJ"]
    source: str
    cut_on: date
    concepts: list[ConceptStatistics]


async def statistics(pool: Any, expedientes: Iterable[str]) -> dict[str, Statistics]:
    files = {
        expediente: key
        for expediente in expedientes
        if (key := file_key(expediente)) is not None
    }
    if not files:
        return {}
    wanted = list(set(files.values()))
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            _LOOKUP,
            [file.year for file in wanted],
            [file.number for file in wanted],
            [file.kind for file in wanted],
            MIN_FILES,
        )
    if not rows:
        return {}
    source = rows[0]
    concepts: dict[FileKey, dict[tuple[str, str], ConceptStatistics]] = {}
    for row in rows:
        file = FileKey(row["number"], row["year"], row["kind"])
        concepts.setdefault(file, {}).setdefault(
            (row["concept"], row["detail"]),
            ConceptStatistics(
                concept=row["concept"],
                detail=row["detail"] or None,
                counts=_counts(row, ""),
                brand=None
                if row["brand_files"] is None
                else BrandCounts(
                    brand=row["brand"], **_counts(row, "brand_").model_dump()
                ),
            ),
        )
    return {
        expediente: Statistics(
            file_type=key.kind,
            source=source["url"],
            cut_on=source["cut_on"],
            concepts=list(concepts[key].values()),
        )
        for expediente, key in files.items()
        if key in concepts
    }


def _counts(row: Any, prefix: str) -> OutcomeCounts:
    return OutcomeCounts(
        files=row[f"{prefix}files"],
        first_year=row[f"{prefix}first_year"],
        last_year=row[f"{prefix}last_year"],
        outcomes={outcome: row[f"{prefix}{outcome}"] for outcome in OUTCOME_KEYS},
    )


_LOOKUP = """
WITH wanted AS (
    SELECT * FROM unnest($1::int[], $2::int[], $3::text[]) AS w (year, number, kind)
),
files AS (
    SELECT DISTINCT ON (year, number, kind) year, number, kind, brand
    FROM outcome_decisions
    JOIN wanted USING (year, number, kind)
    ORDER BY year, number, kind, resolved_on DESC
)
SELECT src.url, src.cut_on, f.year, f.number, f.kind, f.brand, s.concept,
       chosen.detail,
       a.files, a.first_year, a.last_year, a.fundado, a.fundado_en_parte,
       a.infundado, a.improcedente, a.other,
       b.files AS brand_files, b.first_year AS brand_first_year,
       b.last_year AS brand_last_year, b.fundado AS brand_fundado,
       b.fundado_en_parte AS brand_fundado_en_parte,
       b.infundado AS brand_infundado, b.improcedente AS brand_improcedente,
       b.other AS brand_other
FROM outcome_source src
CROSS JOIN files f
JOIN outcome_subjects s USING (year, number, kind)
CROSS JOIN LATERAL (
    SELECT st.detail
    FROM outcome_stats st
    WHERE st.kind = f.kind AND st.concept = s.concept AND st.brand = ''
      AND (st.detail = '' OR (st.detail = s.detail AND st.files >= $4))
    ORDER BY st.detail = ''
    LIMIT 1
) chosen
JOIN outcome_stats a
  ON (a.kind, a.concept, a.detail, a.brand) = (f.kind, s.concept, chosen.detail, '')
LEFT JOIN outcome_stats b
  ON (b.kind, b.concept, b.detail, b.brand) = (f.kind, s.concept, chosen.detail, f.brand)
ORDER BY a.files DESC, s.concept, chosen.detail
"""
