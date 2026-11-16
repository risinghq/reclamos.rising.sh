"""Find the resolutions most like a visitor's description, with their cards.

Nothing here calls a language model: the cards were written and judged offline,
so a visitor's request costs a search and a read.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from reclamos_api.cards import repository
from reclamos_api.cards.card import Points
from reclamos_api.cases.brands import BRANDS, brands_named
from reclamos_api.retrieval.embedder import Embedder
from reclamos_api.retrieval.search import NO_FILTERS, Filters, Hit, search

# Enough chunks to usually hold the ten best distinct resolutions.
CHUNKS = 50
DEFAULT_CASES = 5
MAX_CASES = 10
# The most cases of a brand the query names that go before the rest. A brand
# with few resolutions passes the threshold with cases about another problem,
# so more would push out the cases that match the problem.
NAMED_BRAND_CASES = 2


@dataclass(slots=True)
class Case:
    # The resolution's best passage, which carries its parse fields.
    passage: Hit
    similarity: float
    card: dict[str, Points] | None


async def find_cases(
    pool: Any,
    embedder: Embedder,
    *,
    query: str,
    limit: int = DEFAULT_CASES,
    min_similarity: float,
    filters: Filters = NO_FILTERS,
) -> list[Case]:
    """The best `limit` resolutions with a passage at least `min_similarity`
    similar to `query`, best first. When `query` names a brand, up to
    `NAMED_BRAND_CASES` of that brand's similar cases come first. An empty list
    means no similar case."""
    once = _OneQuery(embedder)
    hits = await search(pool, once, query=query, k=CHUNKS, filters=filters)
    cases = similar_cases(hits, limit=limit, min_similarity=min_similarity)
    named = tuple(name for brand in brands_named(query) for name in BRANDS[brand])
    if named:
        hits = await search(
            pool,
            once,
            query=query,
            k=CHUNKS,
            filters=replace(filters, operators=named),
        )
        first = similar_cases(
            hits, limit=min(limit, NAMED_BRAND_CASES), min_similarity=min_similarity
        )
        cases = _merged(first, cases, limit=limit)
    if cases:
        async with pool.acquire() as connection:
            fields = await repository.served_fields(
                connection, [case.passage.resolution_id for case in cases]
            )
        for case in cases:
            case.card = fields.get(case.passage.resolution_id)
    return cases


def similar_cases(hits: list[Hit], *, limit: int, min_similarity: float) -> list[Case]:
    """One case per resolution, in the order of its best-ranked hit. A
    resolution's similarity is the best cosine similarity of its hits. The fused
    rank orders the cases, and the similarity decides whether one is shown."""
    best: dict[int, Case] = {}
    for hit in hits:
        similarity = hit.vector_score
        case = best.get(hit.resolution_id)
        if case is None:
            best[hit.resolution_id] = Case(hit, similarity or 0.0, None)
        elif similarity is not None and similarity > case.similarity:
            case.similarity = similarity
    kept = [case for case in best.values() if case.similarity >= min_similarity]
    return kept[:limit]


def _merged(first: list[Case], rest: list[Case], *, limit: int) -> list[Case]:
    """`first`, then the cases of `rest` not in it, up to `limit`."""
    seen = {case.passage.resolution_id for case in first}
    return (first + [c for c in rest if c.passage.resolution_id not in seen])[:limit]


class _OneQuery:
    """Embeds the request's query once for all of its searches."""

    def __init__(self, embedder: Embedder) -> None:
        self.model = embedder.model
        self._embedder = embedder
        self._vectors: dict[str, list[float]] = {}

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embedder.embed_passages(texts)

    async def embed_query(self, text: str) -> list[float]:
        if text not in self._vectors:
            self._vectors[text] = await self._embedder.embed_query(text)
        return self._vectors[text]


def outcome_counts(cases: list[Case]) -> dict[str, int]:
    """How many of the cases ended in each outcome, most common first. A case
    whose outcome parse could not read counts under "unknown"."""
    counts = Counter(case.passage.fields["outcome"] or "unknown" for case in cases)
    return dict(counts.most_common())
