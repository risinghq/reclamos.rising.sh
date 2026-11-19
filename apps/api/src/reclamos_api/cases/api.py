"""The `POST /cases` route."""

from dataclasses import replace
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from reclamos_api.cases.brands import brand_of, brands_named
from reclamos_api.cases.find import (
    DEFAULT_CASES,
    MAX_CASES,
    Case,
    find_cases,
    outcome_counts,
)
from reclamos_api.cases.sectors import sector_of
from reclamos_api.outcomes.serve import Statistics, statistics
from reclamos_api.retrieval.api import QueryRequest
from reclamos_api.retrieval.search import IndexModelMismatch
from reclamos_api.rules.find import Rule, find_rules


class CasesRequest(QueryRequest):
    limit: int = Field(default=DEFAULT_CASES, ge=1, le=MAX_CASES)


class Passage(BaseModel):
    ordinal: int
    section: str
    page_start: int
    page_end: int
    text: str


class CardPoint(BaseModel):
    text: str
    quote: str


class FoundCase(BaseModel):
    resolution_id: int
    expediente: str
    sector: str
    number: str | None
    date: date | None
    operator: str | None
    brand: str | None
    claim_type: str | None
    outcome: str | None
    url: str
    pdf_url: str | None
    similarity: float
    is_precedent: bool
    passage: Passage
    # Absent until the resolution has a judged card. Each point is one the
    # judge found backed by its quote.
    card: dict[str, list[CardPoint]] | None
    statistics: Statistics | None


class CasesResponse(BaseModel):
    query: str
    outcome: Literal["found", "no_similar_case"]
    # The sector the request asked for, or the one the query's words imply.
    # None means the query named both sectors or neither and no filter applied.
    sector: str | None
    # The brands the query names, whose cases come first.
    brands: list[str]
    outcomes: dict[str, int]
    cases: list[FoundCase]
    rules: list["FoundRule"]


class FoundRule(BaseModel):
    title: str
    kind: str
    label: str
    approved_by: str
    text_date: date
    pdf_url: str
    text: str


router = APIRouter()


@router.post("/cases")
async def cases(request: Request, body: CasesRequest) -> CasesResponse:
    state = request.app.state
    sector = body.sector or sector_of(body.query)
    filters = replace(body.filters(), sector=sector)
    try:
        found = await find_cases(
            state.pool,
            state.embedder,
            query=body.query,
            limit=body.limit,
            min_similarity=state.min_similarity,
            filters=filters,
        )
        rules: list[Rule] = []
        if found:
            rules = await find_rules(
                state.pool,
                state.embedder,
                query=body.query,
                min_similarity=state.rules_min_similarity,
                min_text_rank=state.rules_min_text_rank,
                sector=sector,
            )
    except IndexModelMismatch as mismatch:
        raise HTTPException(status_code=503, detail=str(mismatch)) from None
    counted = await statistics(
        state.pool, [case.passage.fields["expediente"] for case in found]
    )
    return CasesResponse(
        query=body.query,
        outcome="found" if found else "no_similar_case",
        sector=sector,
        brands=brands_named(body.query),
        outcomes=outcome_counts(found),
        cases=[
            _found_case(case, counted.get(case.passage.fields["expediente"]))
            for case in found
        ],
        rules=[_found_rule(rule) for rule in rules],
    )


def _found_case(case: Case, counted: Statistics | None) -> FoundCase:
    fields = case.passage.fields
    return FoundCase(
        resolution_id=case.passage.resolution_id,
        expediente=fields["expediente"],
        sector=fields["sector"],
        number=fields["number"],
        date=fields["resolved_on"],
        operator=fields["operator"],
        brand=brand_of(fields["operator"]),
        claim_type=fields["claim_type"],
        outcome=fields["outcome"],
        url=fields["page_url"],
        pdf_url=fields["pdf_url"],
        similarity=round(case.similarity, 4),
        is_precedent=fields["is_precedent"],
        passage=Passage(
            ordinal=case.passage.ordinal,
            section=fields["section"],
            page_start=fields["page_start"],
            page_end=fields["page_end"],
            text=fields["text"],
        ),
        card=None
        if case.card is None
        else {
            name: [CardPoint(text=point.text, quote=point.quote) for point in points]
            for name, points in case.card.items()
        },
        statistics=counted,
    )


def _found_rule(rule: Rule) -> FoundRule:
    return FoundRule(
        title=rule.title,
        kind=rule.kind,
        label=rule.label,
        approved_by=rule.approved_by,
        text_date=rule.text_date,
        pdf_url=rule.pdf_url,
        text=rule.text,
    )
