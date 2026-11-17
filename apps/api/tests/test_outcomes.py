import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, Self

import asyncpg
import pytest
from fakeembed import HashingEmbedder
from punku import decision, subject, write_zip
from reclamos_api import cli
from reclamos_api.config import Settings
from reclamos_api.outcomes import repository
from reclamos_api.outcomes.serve import statistics
from reclamos_api.outcomes.source import FileKey, Workbooks, file_key, read_zip
from test_cases import find
from test_search import BILLING, CONTRACT, ENTEL, QUEJA, query

CLARO = "AMERICA MOVIL PERU S.A.C."
ENTEL_SA = "ENTEL PERÚ S.A."
SENTIDOS = ("FUNDADO", "PARCIALMENTE FUNDADO", "INFUNDADO", "IMPROCEDENTE")
DECIDED = date(2022, 6, 1)
LATER = date(2023, 3, 1)


@pytest.mark.parametrize(
    ("expediente", "key"),
    [
        ("0032112-2019/TRASU/ST-RA", FileKey(32112, 2019, "RA")),
        ("Expediente N.° 0000123-2022/TRASU/ST-RA", FileKey(123, 2022, "RA")),
        ("0012550- 2026/TRASU/ST-RA", FileKey(12550, 2026, "RA")),
        ("0014590- 2026/TRASU/STRQJ", FileKey(14590, 2026, "RQJ")),
        ("03665-2016/TRASU/ST-RQJ", FileKey(3665, 2016, "RQJ")),
        ("02038-2009/TRASU/GUS-RA", None),
    ],
    ids=["plain", "with prefix", "space after number", "no hyphen", "short", "gus"],
)
def test_an_expediente_reads_as_number_year_and_type(
    expediente: str, key: FileKey | None
) -> None:
    assert file_key(expediente) == key


def test_the_workbooks_read_every_sheet_layout_and_the_cut_date(
    tmp_path: Path,
) -> None:
    path = write_zip(
        tmp_path / "punku.zip",
        decisions=[
            [decision(5, 2017, "RA", date(2017, 2, 1), "FUNDADO", CLARO)],
            [decision(7, 2025, "RQJ", date(2025, 3, 1), "INFUNDADO", ENTEL_SA)],
        ],
        subjects=[
            [subject(5, 2017, "RA", "FACTURACIÓN", "CARGO FIJO", date(2017, 2, 1))],
            [
                subject(
                    7,
                    2025,
                    "RQJ",
                    "FALTA DE  RESPUESTA AL RECLAMO",
                    "NO APLICA",
                    date(2025, 3, 1),
                )
            ],
        ],
    )

    books = read_zip(path)

    assert [(d.file, d.resolved_on, d.sentido, d.company) for d in books.decisions] == [
        (FileKey(5, 2017, "RA"), date(2017, 2, 1), "FUNDADO", CLARO),
        (FileKey(7, 2025, "RQJ"), date(2025, 3, 1), "INFUNDADO", ENTEL_SA),
    ]
    assert [(s.file, s.concepto, s.subconcepto) for s in books.subjects] == [
        (FileKey(5, 2017, "RA"), "FACTURACIÓN", "CARGO FIJO"),
        (FileKey(7, 2025, "RQJ"), "FALTA DE RESPUESTA AL RECLAMO", "NO APLICA"),
    ]
    assert books.cut_on == date(2026, 7, 24)


def billing_zip(path: Path) -> Path:
    claro = range(100, 220)
    return write_zip(
        path,
        decisions=[
            [
                decision(101, 2022, "RA", date(2022, 1, 3), "ANULADO", CLARO),
                *(
                    decision(n, 2022, "RA", DECIDED, SENTIDOS[n % 4], CLARO)
                    for n in claro
                ),
            ],
            [decision(n, 2023, "RA", LATER, "ARCHIVAR", ENTEL_SA) for n in (1, 2, 3)],
        ],
        subjects=[
            [
                *(
                    subject(n, 2022, "RA", "FACTURACIÓN", "CARGO FIJO", DECIDED)
                    for n in claro
                ),
                subject(100, 2022, "RA", "FACTURACIÓN", "CARGO FIJO", DECIDED),
                subject(123, 2022, "RA", "CALIDAD", "AVERIA DEL SERVICIO", DECIDED),
                subject(124, 2022, "RA", "UNA MATERIA NUEVA", "NO APLICA", DECIDED),
            ],
            [
                subject(n, 2023, "RA", "FACTURACIÓN Y COBRO", "Cargo fijo", LATER)
                for n in (1, 2, 3)
            ],
        ],
    )


@pytest.mark.integration
def test_a_case_whose_file_matches_gets_the_tribunal_counts_and_others_none(
    indexed: Settings,
    embedder: HashingEmbedder,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    query(
        indexed,
        "UPDATE resolutions SET expediente = '0000999-2023/TRASU/ST-RA' WHERE id = $1",
        ENTEL,
    )

    cli.main(["outcomes", "load", "--zip", str(billing_zip(tmp_path / "punku.zip"))])

    printed = capsys.readouterr().out
    assert "decisions by year:\n  2022 121\n  2023 3\n" in printed
    assert "concept labels not in the table: 1\n  UNA MATERIA NUEVA 1\n" in printed
    assert "corpus: 3 of 4 expedientes numbered 2016 or later match a file" in printed
    found = find(
        indexed,
        embedder,
        monkeypatch,
        0.0,
        query="cobro de un servicio no reconocido en el recibo",
        limit=10,
    )
    cases = {case["resolution_id"]: case for case in found["cases"]}
    assert cases[ENTEL]["statistics"] is None
    billing: dict[str, Any] = {
        "file_type": "RA",
        "source": "https://punku.osiptel.gob.pe/Archivos/Datasets-PUNKU-OSIPTEL.zip",
        "cut_on": "2026-07-24",
        "concepts": [
            {
                "concept": "facturación y cobro",
                "detail": "cargo fijo",
                "counts": {
                    "files": 123,
                    "first_year": 2022,
                    "last_year": 2023,
                    "outcomes": {
                        "fundado": 30,
                        "fundado_en_parte": 30,
                        "infundado": 30,
                        "improcedente": 30,
                        "other": 3,
                    },
                },
                "brand": {
                    "brand": "Claro",
                    "files": 120,
                    "first_year": 2022,
                    "last_year": 2022,
                    "outcomes": {
                        "fundado": 30,
                        "fundado_en_parte": 30,
                        "infundado": 30,
                        "improcedente": 30,
                        "other": 0,
                    },
                },
            },
            {
                "concept": "calidad del servicio",
                "detail": None,
                "counts": {
                    "files": 1,
                    "first_year": 2022,
                    "last_year": 2022,
                    "outcomes": {
                        "fundado": 0,
                        "fundado_en_parte": 0,
                        "infundado": 0,
                        "improcedente": 1,
                        "other": 0,
                    },
                },
                "brand": None,
            },
        ],
    }
    for matched in (BILLING, CONTRACT, QUEJA):
        assert cases[matched]["statistics"] == billing


class ReloadAfterFirstRead:
    def __init__(
        self, connection: Any, reload: Callable[[], Awaitable[object]]
    ) -> None:
        self._connection = connection
        self._reload: Callable[[], Awaitable[object]] | None = reload

    def acquire(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def fetch(self, *arguments: Any) -> Any:
        return await self._after(await self._connection.fetch(*arguments))

    async def fetchrow(self, *arguments: Any) -> Any:
        return await self._after(await self._connection.fetchrow(*arguments))

    async def _after(self, result: Any) -> Any:
        if self._reload is not None:
            reload, self._reload = self._reload, None
            await reload()
        return result


@pytest.mark.integration
def test_a_reload_during_the_lookup_never_pairs_a_cut_date_with_other_counts(
    indexed: Settings, tmp_path: Path
) -> None:
    cli.main(["outcomes", "load", "--zip", str(billing_zip(tmp_path / "punku.zip"))])
    file = "0000150-2022/TRASU/ST-RA"
    later: Workbooks = replace(
        read_zip(
            write_zip(
                tmp_path / "later.zip",
                decisions=[[decision(150, 2022, "RA", DECIDED, "FUNDADO", CLARO)]],
                subjects=[
                    [subject(150, 2022, "RA", "FACTURACIÓN", "CARGO FIJO", DECIDED)]
                ],
            )
        ),
        cut_on=date(2026, 10, 1),
    )

    async def look_up() -> tuple[date, int, date]:
        reader = await asyncpg.connect(indexed.database_url)
        reloader = await asyncpg.connect(indexed.database_url)
        try:
            served = await statistics(
                ReloadAfterFirstRead(reader, lambda: repository.load(reloader, later)),
                [file],
            )
            reloaded = await reloader.fetchval("SELECT cut_on FROM outcome_source")
        finally:
            await reader.close()
            await reloader.close()
        return served[file].cut_on, served[file].concepts[0].counts.files, reloaded

    assert asyncio.run(look_up()) == (date(2026, 7, 24), 123, date(2026, 10, 1))
