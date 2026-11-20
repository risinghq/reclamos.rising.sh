import json
import re

import pytest
from fakeembed import HashingEmbedder
from fakemodel import FakeModel, as_rewritten
from reclamos_api import cli
from reclamos_api.cards import card, judge
from reclamos_api.config import Settings
from reclamos_api.llm.client import NotBilled, Prompt, ProviderFailed
from test_search import BILLING, CONTRACT, ENTEL, QUEJA, query

INVENTED = "el tribunal ordenó devolver diez mil soles al usuario"
# Lines of the BILLING fixture, which parse reads as INFUNDADO, AMERICA MOVIL
# PERU S.A.C. and 2022-08-24.
OUTCOME_LINE = "Declarar INFUNDADO el Recurso de Apelación"
OPERATOR_LINE = "EMPRESA OPERADORA : AMERICA MOVIL PERU S.A.C."
DATE_LINE = "Lima, 24 de agosto de 2022"


def body_of(prompt: Prompt) -> str:
    return prompt.text.split("Texto de la resolución:\n\n", 1)[1]


def point(text: str, quote: str) -> dict[str, str]:
    return {"text": text, "quote": quote}


def reading(value: str, quote: str) -> dict[str, str]:
    return {"value": value, "quote": quote}


def card_or_verdict(prompt: Prompt) -> str:
    """A card that quotes the body it was sent, with a point on an invented
    quote, a field backed only by that quote, a point with no text, and a
    misread outcome. A verdict that flags the first claim point."""
    if prompt.system in judge.SYSTEMS.values():
        return json.dumps(
            {"unsupported": [{"field": "claim", "point": 1, "claim": "reclamó"}]}
        )
    body = body_of(prompt)
    operator = reading("América Móvil Perú S.A.C.", OPERATOR_LINE)
    if prompt.system == card.SYSTEMS["energy"]:
        concesionaria = re.search(r"Concesionaria: ([^\n]+)", body)
        assert concesionaria
        expediente = re.search(r"Expediente N.° 2025000000(\d\d)", body)
        assert expediente
        operator = reading(
            OPERATOR_READINGS.get(expediente[1], concesionaria[1]),
            concesionaria[0],
        )
    return json.dumps(
        {
            "claim": [
                point("El usuario reclamó.", as_rewritten(body[400:520])),
                point("Pidió diez mil soles.", INVENTED),
            ],
            "operator_position": [point("La empresa devolvió todo.", INVENTED)],
            "reasoning": [],
            "evidence": [
                point("Faltó la prueba.", body[1000:1100]),
                point("", body[1100:1200]),
            ],
            "outcome": reading("fundado", OUTCOME_LINE),
            "operator": operator,
            "resolved_on": reading("2022-08-24", DATE_LINE),
        }
    )


def cards(*argv: str, model: FakeModel, capsys: pytest.CaptureFixture[str]) -> str:
    cli.main(["cards", *argv], model=model)
    return capsys.readouterr().out


@pytest.mark.integration
def test_cards_are_built_within_a_budget_checked_judged_and_reported(
    indexed: Settings,
    embedder: HashingEmbedder,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The budget binds only on a priced writer, and the default one is free.
    monkeypatch.setenv("CARD_MODEL", "claude-sonnet-5-5")
    # Each card reserves about US$0.04 and, at 3,000 output tokens, is billed
    # about US$0.03. The second card cannot fit in US$0.06.
    model = FakeModel(card_or_verdict, output_tokens=3000)
    out = cards(
        "build",
        "--budget-usd",
        "0.06",
        "--concurrency",
        "1",
        model=model,
        capsys=capsys,
    )
    assert "cards written: 1 of 4 without a current card" in out
    assert "stopped: the run has spent" in out
    assert len(model.prompts) == 1

    model.error = NotBilled("400: usage limit reached")
    out = cards(
        "build", "--budget-usd", "1", "--concurrency", "1", model=model, capsys=capsys
    )
    assert "cards written: 0 of 3" in out
    assert "stopped: the provider refused: 400: usage limit reached" in out
    assert len(model.prompts) == 2, "a provider refusal stops the run"

    model.error = ProviderFailed("APITimeoutError()")
    out = cards(
        "build", "--budget-usd", "1", "--concurrency", "1", model=model, capsys=capsys
    )
    assert "cards written: 0 of 3" in out
    assert f"unreadable {CONTRACT}: the provider failed: APITimeoutError()" in out
    assert "stopped" not in out
    assert len(model.prompts) == 5, "a provider failure skips only its own card"

    model.error = None
    model.output_tokens = 20
    out = cards("build", "--budget-usd", "1", model=model, capsys=capsys)
    assert "cards written: 3 of 3 without a current card" in out
    assert "stopped" not in out
    out = cards("build", "--budget-usd", "1", model=model, capsys=capsys)
    assert "cards written: 0 of 0" in out
    assert len(model.prompts) == 8, "a current card is not written again"
    assert all(p.model == "claude-sonnet-5-5" for p in model.prompts)

    rows = query(indexed, "SELECT * FROM cards ORDER BY resolution_id")
    assert [r["resolution_id"] for r in rows] == [BILLING, CONTRACT, QUEJA, ENTEL]
    billing = rows[0]
    fields = json.loads(billing["fields"])
    assert set(fields) == {"claim", "evidence"}, (
        "a field with only invented quotes, or with no point, is dropped"
    )
    assert [p["text"] for p in fields["claim"]] == ["El usuario reclamó."]
    assert len(fields["evidence"]) == 1, "a point with no text is dropped"
    rejected = json.loads(billing["rejected"])
    for name, text in [
        ("claim", "Pidió diez mil soles."),
        ("operator_position", "La empresa devolvió todo."),
    ]:
        assert {"field": name, "text": text, "quote": INVENTED} in rejected
    assert set(json.loads(billing["readings"])) == {
        "outcome",
        "operator",
        "resolved_on",
    }
    entel = json.loads(rows[3]["readings"])
    assert "operator" not in entel and "resolved_on" not in entel, (
        "a reading quoting another resolution's lines is rejected"
    )

    out = cards("judge", "--budget-usd", "1", model=model, capsys=capsys)
    assert "cards judged: 4 of 4 without a verdict" in out
    judged = model.prompts[8]
    assert judged.system == judge.SYSTEMS["telecom"]
    assert "claim 1: El usuario reclamó.\nCita: «" in judged.text
    assert fields["claim"][0]["quote"] in judged.text
    assert INVENTED not in judged.text, "the judge reads only the checked card"

    out = cards("report", model=model, capsys=capsys)
    assert "cards: 4 (4 current)" in out
    assert (
        "points: claim 4, operator_position 0, reasoning 0, evidence 4, orders 0" in out
    )
    assert "dropped: 12 points" in out
    assert "judged: 4, faithful 0 (0.0%)" in out
    assert "unsupported points by field: claim 4" in out
    assert "points served: 4 of 8 judged (50.0%)" in out
    assert "disagreements with parse: 2" in out
    for resolution in (BILLING, CONTRACT):
        assert f"{resolution} outcome: parse infundado, card fundado" in out, (
            "the operator matches parse on its letters, the date on its value"
        )


JARU = 8000001
# A JARU-style body, long enough for the fake reply's quotes.
JARU_BODY = """\
RESOLUCIÓN DE LA SALA UNIPERSONAL 1
JUNTA DE APELACIONES DE RECLAMOS DE USUARIOS
ORGANISMO SUPERVISOR DE LA INVERSIÓN EN ENERGÍA Y MINERÍA
OSINERGMIN N.° 0001-2025-OS/JARU-S1
Lima, 15 de enero de 2025

Expediente N.° 202500000001
Concesionaria: Pluz Energía Perú S.A.A.
Materia: Excesivos consumos facturados

1. ANTECEDENTES

1.1 El usuario reclamó por excesivos consumos facturados en su suministro
eléctrico. Manifestó que el medidor registra consumos que no corresponden a su
uso real del servicio desde hace tres meses.

1.2 La concesionaria declaró infundado el reclamo mediante la Resolución
N.° 100000001, sosteniendo que las lecturas del medidor fueron verificadas y no
presentaron diferencias con lo facturado.

1.3 El usuario presentó recurso de apelación contra la citada resolución,
manifestando que la concesionaria no realizó la prueba de contraste del medidor
que había solicitado.

2. ANÁLISIS

2.1 La concesionaria no acreditó haber realizado la prueba de contraste que el
usuario solicitó, por lo que la facturación reclamada carece de sustento.

3. RESOLUCIÓN

SE RESUELVE: Declarar FUNDADO el recurso de apelación y, en consecuencia,
ordenar a la concesionaria emitir un nuevo pronunciamiento sobre el reclamo e
informar a Osinergmin y al usuario el cumplimiento de lo dispuesto.
"""

# The operator the card reads from each seeded JARU body, by the last two
# digits of its expediente. Each names the company its Concesionaria line
# gives — as a trade name, an acronym or another legal form — except the
# generic "empresa distribuidora", which is a real disagreement.
OPERATOR_READINGS = {
    "02": "Gas Natural de Lima y Callao S.A. - Cálidda",
    "03": "Gas Natural de Lima y Callao S.A. — Cálidda",
    "04": "Cálidda — Gas Natural de Lima y Callao S.A.",
    "05": "Cálidda",
    "06": "GNLC",
    "07": "Hidrandina S.A.",
    "08": "empresa distribuidora",
    "09": "Electro Sur Este S.A.A.",
}
CONCESIONARIAS = {
    "07": ("Hidrandina S.A.A.", "HIDRANDINA S.A.A."),
    "09": ("Electro Sur Este S.A.", "ELECTRO SUR ESTE S.A."),
}


def jaru_body(expediente: str, concesionaria: str) -> str:
    return JARU_BODY.replace("202500000001", f"2025000000{expediente}").replace(
        "Concesionaria: Pluz Energía Perú S.A.A.",
        f"Concesionaria: {concesionaria}",
    )


@pytest.mark.integration
def test_each_sector_builds_and_judges_under_its_own_prompt(
    indexed: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query(
        indexed,
        """
        INSERT INTO resolutions (id, page_url, expediente, published_on, sector,
                                 body)
        VALUES ($1, 'https://www.gob.pe/x', '0001-2025-OS/JARU-S1',
                '2025-01-15', 'energy', $2)
        """,
        JARU,
        JARU_BODY,
    )
    for expediente in OPERATOR_READINGS:
        concesionaria, operator = CONCESIONARIAS.get(
            expediente,
            ("Gas Natural de Lima y Callao S.A.", "GAS NATURAL DE LIMA Y CALLAO S.A."),
        )
        query(
            indexed,
            """
            INSERT INTO resolutions (id, page_url, expediente, published_on,
                                     sector, body, operator)
            VALUES ($1, 'https://www.gob.pe/x', $3, '2025-01-15', 'energy',
                    $2, $4)
            """,
            JARU + int(expediente),
            jaru_body(expediente, concesionaria),
            f"00{expediente}-2025-OS/JARU-S1",
            operator,
        )
    model = FakeModel(card_or_verdict)

    out = cards(
        "build", "--budget-usd", "1", "--sector", "telecom", model=model, capsys=capsys
    )
    assert "cards written: 4 of 4 without a current card" in out
    assert all(p.system == card.SYSTEMS["telecom"] for p in model.prompts)

    out = cards(
        "build", "--budget-usd", "1", "--sector", "energy", model=model, capsys=capsys
    )
    assert "cards written: 9 of 9 without a current card" in out
    assert model.prompts[-1].system == card.SYSTEMS["energy"]

    out = cards("build", "--budget-usd", "1", model=model, capsys=capsys)
    assert "cards written: 0 of 0" in out, (
        "a card current under its sector's prompt is not written again"
    )

    out = cards(
        "judge", "--budget-usd", "1", "--sector", "energy", model=model, capsys=capsys
    )
    assert "cards judged: 9 of 9 without a verdict" in out
    assert model.prompts[-1].system == judge.SYSTEMS["energy"]

    out = cards("report", "--sector", "energy", model=model, capsys=capsys)
    assert "cards: 9 (9 current)" in out
    assert "judged: 9, faithful 0" in out
    assert "disagreements with parse: 1" in out
    assert (
        "8000009 operator: parse GAS NATURAL DE LIMA Y CALLAO S.A.,"
        " card empresa distribuidora" in out
    ), "a dash-joined trade name, an acronym or a legal form is the company"
    out = cards("report", model=model, capsys=capsys)
    assert "cards: 13 (13 current)" in out
