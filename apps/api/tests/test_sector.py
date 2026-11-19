import asyncio
from pathlib import Path

import pytest
from fakeembed import HashingEmbedder
from fastapi.testclient import TestClient
from reclamos_api.cases.sectors import sector_of
from reclamos_api.config import Settings
from reclamos_api.corpus.sources import OSINERGMIN, OSIPTEL
from reclamos_api.main import create_app
from test_search import BILLING, bodies, seed_and_run

pytestmark = pytest.mark.integration

JARU = 7000001
JARU_BODY = """RESOLUCIÓN DE LA SALA UNIPERSONAL 2
JUNTA DE APELACIONES DE RECLAMOS DE USUARIOS
ORGANISMO SUPERVISOR DE LA INVERSIÓN EN ENERGÍA Y MINERÍA
OSINERGMIN N° 5981-2024 OS/JARU-S2

Expediente N° 202400110013
Recurrente: Juana Perez
Empresa distribuidora: Luz del Sur S.A.A.
Materia: Excesivas facturaciones
Suministro: N° 138734

Lima, 15 de enero del 2024

VISTOS, los antecedentes del expediente, y:

SE RESUELVE:
Artículo 1.- REVOCAR la Resolución impugnada y, reformándola,
declarar FUNDADO el reclamo por excesivas facturaciones.
"""


@pytest.fixture
def mixed(settings: Settings, embedder: HashingEmbedder, tmp_path: Path) -> Settings:
    billing = bodies()[BILLING]
    asyncio.run(
        seed_and_run(
            settings,
            embedder,
            tmp_path / "pdfs",
            texts={BILLING: billing, JARU: JARU_BODY},
            sources={JARU: OSINERGMIN},
            expedientes={JARU: "5981-2024-OS/JARU-S2"},
        )
    )
    return settings


def test_osinergmin_keeps_only_jaru() -> None:
    listed = OSINERGMIN.expediente("Resolución Administrativa N.° 5981-2024 OS/JARU-S2")
    assert OSINERGMIN.keep(listed) == "5981-2024-OS/JARU-S2"
    assert OSINERGMIN.keep("5981-2024-OS/JARU-S2") == "5981-2024-OS/JARU-S2"
    assert OSINERGMIN.skip("5981-2024-OS/JARU-S2") is None
    assert OSINERGMIN.skip("008-2003-OS/CC-04-CP") == "cuerpo_colegiado"
    assert OSINERGMIN.skip("004-2003-OS/TSC-01") == "tribunal_controversias"
    assert OSINERGMIN.skip("123-2020-OS/GFS") == "not_jaru"
    assert OSIPTEL.skip("0038402-2022/TRASU/ST-RQJ") is None


def test_sector_inference() -> None:
    assert sector_of("me cobraron de más en el recibo de luz") == "energy"
    assert sector_of("cálidda me cortó el gas") == "energy"
    assert sector_of("me subió la factura del celular") == "telecom"
    assert sector_of("me cobran un servicio que no reconozco") is None


def test_a_search_filtered_by_sector_keeps_out_the_other(
    mixed: Settings, embedder: HashingEmbedder
) -> None:
    with TestClient(create_app(embedder)) as client:
        for sector in ("energy", "telecom"):
            response = client.post(
                "/search", json={"query": "facturación excesiva", "sector": sector}
            )
            assert response.status_code == 200, response.text
            sectors = {hit["sector"] for hit in response.json()["results"]}
            assert sectors == {sector}


def test_a_question_about_recibo_de_luz_never_returns_a_telecom_case(
    mixed: Settings,
    embedder: HashingEmbedder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFUSAL_MIN_SIMILARITY", "0")
    with TestClient(create_app(embedder)) as client:
        response = client.post(
            "/cases", json={"query": "me cobraron de más en el recibo de luz"}
        )
    assert response.status_code == 200, response.text
    found = response.json()
    assert found["sector"] == "energy"
    assert found["cases"], "the JARU case should be found"
    assert {case["sector"] for case in found["cases"]} == {"energy"}
