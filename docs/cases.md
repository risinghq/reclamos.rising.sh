# Cases

`POST /cases` takes a visitor's description of their problem and returns the
resolutions most like it, each with its [card](cards.md) when one is served. It
makes no model call: the cards were written and judged offline. The code is in
`apps/api/src/reclamos_api/cases/`.

| File        | Owns                                                   |
| ----------- | ------------------------------------------------------ |
| `find.py`   | The search, the grouping by resolution and the cut-off |
| `brands.py` | The brands visitors name and their legal names         |
| `api.py`    | The `POST /cases` route                                |

## Finding cases

`find_cases` takes these steps:

1. Search the description in hybrid mode for the best 50 chunks, with the
   request's filters.
2. Group the chunks by resolution, in the order of each resolution's best-ranked
   chunk. A resolution's similarity is the best cosine similarity of its chunks.
3. Drop every resolution below `REFUSAL_MIN_SIMILARITY` and keep the first
   `limit`.
4. When the description names a brand, run steps 1 to 3 again for that brand's
   legal names only. Up to `NAMED_BRAND_CASES` (2) of those cases go first, and
   the cases of step 3 follow without repeats, still up to `limit`.
5. Attach each kept resolution's served card fields.

A resolution names the company by its legal name at the time, so `brands.py`
maps each legal name to the brand a visitor knows: TIM and Telmex are Claro,
Nextel is Entel, Telefónica and Integratel are Movistar, Viettel is Bitel. A
brand word matches without case or accents. The cap is 2 because a brand with
few resolutions clears the threshold with cases about other problems. Without a
cap, a Bitel billing question filled all 5 slots with Bitel cases, 4 of them
procedural.

A card is served while it and its verdict are current: its `prompt_version`
matches the code, its `body_sha256` matches the body, and its `judge_version`
matches the judge. A point the judge listed as unsupported is not served. A
field with no point left is not served, and neither is a card with no field
left. A case without a served card still shows its best passage.

## Route

The request takes `query` and the filters of [`POST /search`](retrieval.md):
`claim_type`, `operator`, `outcome`, `date_from` and `date_to`. `limit` is 1 to
10 and defaults to 5. Any other field answers 422.

```json
{
  "query": "Me cobran un servicio que no contraté",
  "outcome": "found",
  "brands": ["Movistar"],
  "outcomes": { "fundado": 3, "infundado": 2 },
  "cases": [
    {
      "resolution_id": 4211,
      "expediente": "...",
      "number": "...",
      "date": "2024-03-18",
      "operator": "TELEFONICA DEL PERU S.A.A.",
      "brand": "Movistar",
      "claim_type": "unrequested_contract",
      "outcome": "fundado",
      "url": "https://www.gob.pe/...",
      "pdf_url": "https://cdn.www.gob.pe/...pdf",
      "similarity": 0.8731,
      "passage": {
        "ordinal": 7,
        "section": "...",
        "page_start": 3,
        "page_end": 3,
        "text": "..."
      },
      "card": {
        "claim": [{ "text": "...", "quote": "..." }],
        "reasoning": [
          { "text": "...", "quote": "..." },
          { "text": "...", "quote": "..." }
        ]
      }
    }
  ]
}
```

`brands` lists the brands the query names. `brand` is null for a legal name
`brands.py` does not map. `url` is the resolution's gob.pe page and `pdf_url`
the PDF it links to.

`outcomes` counts the returned cases by outcome, most common first. A case whose
outcome parse could not read counts under `unknown`. When no resolution reaches
the threshold, `outcome` is `no_similar_case` and `cases` is empty. The route
answers 503 when the index was embedded with another model.

## Threshold

`REFUSAL_MIN_SIMILARITY` defaults to `0.84`. On the full corpus (2026-11-14) the
lowest best similarity of the 116 answerable questions was 0.844. The 12
unanswerable questions ranged from 0.803 to 0.862. The two ranges overlap, so no
threshold refuses every unanswerable question and keeps every answerable one. At
`0.84` every answerable question still finds cases and half the unanswerable
ones find none. At `0.85` 1.7% of answerable questions lost their cases, and at
`0.86` 14.7% did.

A case above the threshold can still be unrelated to the visitor's problem. The
web app presents the results as similar cases, never as an answer to the
visitor's question.

## Tests

`test_cases.py` builds the fixture index and serves cards in each state through
the route: current and judged with flagged points, judged by an older judge,
written from an older body and written by an older prompt. It also checks the
response below the threshold and that a named brand's case moves first while the
rest keep their order. `test_brands.py` checks the brand words and the
legal-name map. No test sets an API key.
