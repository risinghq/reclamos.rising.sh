import asyncio
import json
from datetime import date
from typing import Any

import httpx2
import pytest
from fakeembed import HashingEmbedder
from fastapi.testclient import TestClient
from reclamos_api.cards.card import PROMPT_VERSIONS
from reclamos_api.cards.judge import JUDGE_VERSIONS
from reclamos_api.cards.repository import body_sha256
from reclamos_api.config import Settings
from reclamos_api.corpus.repository import vector_literal
from reclamos_api.main import create_app
from test_search import BILLING, CONTRACT, ENTEL, QUEJA, bodies, query

pytestmark = pytest.mark.integration

CLAIM = [
    {"text": "El usuario reclama un cobro.", "quote": "q1"},
    {"text": "Pide que se anule.", "quote": "q2"},
]
EVIDENCE = [{"text": "La empresa presentó su registro.", "quote": "q3"}]


def save_card(
    settings: Settings,
    resolution_id: int,
    *,
    prompt_version: str = PROMPT_VERSIONS["telecom"],
    body: str | None = None,
    unsupported: list[dict[str, Any]] | None = None,
    judge_version: str = JUDGE_VERSIONS["telecom"],
) -> None:
    """A card with a claim and evidence. `unsupported` None leaves it unjudged.
    `judge_version` is the judge prompt that gave the verdict."""
    query(
        settings,
        """
        INSERT INTO cards (resolution_id, prompt_version, body_sha256, model,
                           fields, readings, rejected, usd,
                           judge_model, judge_version, unsupported, judged_at)
        VALUES ($1, $2, $3, 'm', $4::jsonb, '{}', '[]', 0, $5, $7, $6::jsonb,
                CASE WHEN $6::jsonb IS NULL THEN NULL ELSE now() END)
        """,
        resolution_id,
        prompt_version,
        body_sha256(body if body is not None else bodies()[resolution_id]),
        json.dumps({"claim": CLAIM, "evidence": EVIDENCE}),
        None if unsupported is None else "judge",
        None if unsupported is None else json.dumps(unsupported),
        None if unsupported is None else judge_version,
    )


def find(
    settings: Settings,
    embedder: HashingEmbedder,
    monkeypatch: pytest.MonkeyPatch,
    min_similarity: float,
    **body: Any,
) -> dict[str, Any]:
    monkeypatch.setenv("REFUSAL_MIN_SIMILARITY", str(min_similarity))
    with TestClient(create_app(embedder)) as test_client:
        client: httpx2.Client = test_client
        response = client.post("/cases", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_cases_group_by_resolution_and_serve_only_current_judged_points(
    indexed: Settings, embedder: HashingEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_card(
        indexed,
        BILLING,
        unsupported=[
            {"field": "claim", "point": 2, "claim": "x"},
            {"field": "evidence", "point": 1, "claim": "y"},
        ],
    )
    save_card(indexed, CONTRACT, unsupported=[], judge_version="old")
    save_card(indexed, QUEJA, body="an older text", unsupported=[])
    save_card(indexed, ENTEL, prompt_version="old", unsupported=[])

    found = find(
        indexed,
        embedder,
        monkeypatch,
        0.0,
        query="cobro de un servicio no reconocido en el recibo",
        limit=10,
    )

    assert found["outcome"] == "found"
    cases = {case["resolution_id"]: case for case in found["cases"]}
    assert len(cases) == len(found["cases"]), "one case per resolution"
    assert set(cases) == {BILLING, CONTRACT, QUEJA, ENTEL}
    assert sum(found["outcomes"].values()) == len(cases)
    assert cases[BILLING]["card"] == {"claim": CLAIM[:1]}, (
        "a flagged point is dropped, and a field with no point left"
    )
    for unserved, why in [
        (CONTRACT, "judged by another judge prompt"),
        (QUEJA, "written from another body"),
        (ENTEL, "written by another prompt"),
    ]:
        assert cases[unserved]["card"] is None, why
    similarities = [case["similarity"] for case in found["cases"]]
    assert all(0 <= s <= 1 for s in similarities)


def test_no_case_is_shown_below_the_similarity_threshold(
    indexed: Settings, embedder: HashingEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = find(indexed, embedder, monkeypatch, 1.01, query="cobro indebido")

    assert found == {
        "query": "cobro indebido",
        "outcome": "no_similar_case",
        "sector": None,
        "brands": [],
        "outcomes": {},
        "cases": [],
        "rules": [],
    }


def test_a_named_brand_puts_its_cases_first_and_keeps_the_rest_in_order(
    indexed: Settings, embedder: HashingEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = "me activaron un contrato que no solicité"
    plain = find(indexed, embedder, monkeypatch, 0.0, query=problem, limit=10)
    named = find(
        indexed, embedder, monkeypatch, 0.0, query=f"Entel: {problem}", limit=10
    )

    order = [case["resolution_id"] for case in plain["cases"]]
    assert order[0] != ENTEL, "without the brand another case ranks first"
    assert named["brands"] == ["Entel"]
    assert [case["resolution_id"] for case in named["cases"]] == [ENTEL] + [
        resolution for resolution in order if resolution != ENTEL
    ]
    brands = {case["resolution_id"]: case["brand"] for case in named["cases"]}
    assert brands[ENTEL] == "Entel" and brands[BILLING] == "Claro"
    assert all(case["pdf_url"] for case in named["cases"])


def test_cases_serves_current_rules_next_to_similar_cases(
    indexed: Settings, embedder: HashingEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULES_MIN_SIMILARITY", "0")
    vector = asyncio.run(
        embedder.embed_passages(["La empresa debe anular el cobro no reconocido."])
    )[0]
    query(
        indexed,
        """
        INSERT INTO rule_documents (slug, title, kind, approved_by, text_date, pdf_url,
                                    pdf_key, pdf_sha256, body, build_sha256)
        VALUES ('reglamento', 'Reglamento de Reclamos', 'reglamento', 'Res. 099',
                $1, 'https://rules.test/reglamento.pdf', 'rules/reglamento.pdf',
                'hash', 'Artículo 48', 'build')
        """,
        date(2026, 10, 3),
    )
    query(
        indexed,
        """
        INSERT INTO rule_passages (document_slug, ordinal, label, text_source, text_date,
                                   pdf_url, text, embedding)
        VALUES ('reglamento', 0, 'Artículo 48', 'Res. 000129-2026-CD/OSIPTEL',
                $1, 'https://rules.test/reglamento.pdf', $2, $3::vector)
        """,
        date(2026, 10, 3),
        "La empresa debe anular el cobro no reconocido.",
        vector_literal(vector),
    )

    found = find(
        indexed,
        embedder,
        monkeypatch,
        0.0,
        query="cobro no reconocido que debe anularse",
    )

    assert found["rules"] == [
        {
            "title": "Reglamento de Reclamos",
            "kind": "reglamento",
            "label": "Artículo 48",
            "approved_by": "Res. 000129-2026-CD/OSIPTEL",
            "text_date": "2026-10-03",
            "pdf_url": "https://rules.test/reglamento.pdf",
            "text": "La empresa debe anular el cobro no reconocido.",
        }
    ]

    no_similar_case = find(
        indexed,
        embedder,
        monkeypatch,
        1.01,
        query="cobro no reconocido que debe anularse",
    )

    assert no_similar_case["outcome"] == "no_similar_case"
    assert no_similar_case["rules"] == []


def test_cases_excludes_nonvisitor_and_nonlexical_rules(
    indexed: Settings, embedder: HashingEmbedder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RULES_MIN_SIMILARITY", "0")
    monkeypatch.setenv("RULES_MIN_TEXT_RANK", "0")
    vector = asyncio.run(embedder.embed_query("cobro no reconocido"))
    for slug, title, searchable, text in (
        (
            "sanciones",
            "Precedente sancionador",
            False,
            "Cobro no reconocido en una multa administrativa.",
        ),
        (
            "generico",
            "Pasaje genérico",
            True,
            "La resolución cumple el procedimiento administrativo.",
        ),
        (
            "regla",
            "Reglamento de Reclamos",
            True,
            "El usuario puede reclamar un cobro no reconocido.",
        ),
    ):
        query(
            indexed,
            """
            INSERT INTO rule_documents (slug, title, kind, approved_by, text_date, pdf_url,
                                        pdf_key, pdf_sha256, body, source_sha256, build_sha256,
                                        visitor_searchable)
            VALUES ($1, $2, 'precedente', 'Res. 1', $3, 'https://rules.test/rule.pdf',
                    'rules/rule.pdf', $1, $4, 'source', 'build', $5)
            """,
            slug,
            title,
            date(2026, 1, 1),
            text,
            searchable,
        )
        query(
            indexed,
            """
            INSERT INTO rule_passages (document_slug, ordinal, label, text_source, text_date,
                                       pdf_url, text, embedding)
            VALUES ($1, 0, 'Pasaje 1', 'Res. 1', $2, 'https://rules.test/rule.pdf', $3,
                    $4::vector)
            """,
            slug,
            date(2026, 1, 1),
            text,
            vector_literal(vector),
        )

    found = find(
        indexed,
        embedder,
        monkeypatch,
        0.0,
        query="cobro no reconocido",
    )

    assert [rule["title"] for rule in found["rules"]] == ["Reglamento de Reclamos"]
