import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fakeembed import HashingEmbedder
from reclamos_api.corpus.redact import Redactor
from reclamos_api.corpus.store import LocalStore
from reclamos_api.db import database_pool
from reclamos_api.rules.sources import Changes, RuleSource
from reclamos_api.rules.sync import (
    ConsolidationError,
    consolidate,
    split_document,
    split_parts,
    sync,
)
from textpdf import text_pdf

pytestmark = pytest.mark.integration

BASE = RuleSource(
    "reglamento",
    "Reglamento de prueba",
    "reglamento",
    "Res. 1",
    date(2022, 1, 1),
    "https://rules.test/base.pdf",
)
AMENDMENT = RuleSource(
    "modificatoria",
    "Modificatoria de prueba",
    "modificatoria",
    "Res. 2",
    date(2023, 1, 1),
    "https://rules.test/amendment.pdf",
    Changes(
        modifies=("Artículo 1",),
        incorporates=("Artículo 2-A",),
        repeals=("Artículo 2",),
    ),
    "reglamento",
)
BASE_TEXT = """Artículo 1.- Original
Texto original de facturación.
Artículo 2.- Derogado
Texto que se deroga."""
AMENDMENT_TEXT = """Artículo 1.- Modificado
Texto vigente de facturación.
Artículo 2-A.- Incorporado
Texto nuevo para reclamos."""


def test_consolidation_refuses_a_declared_article_missing_from_the_amendment() -> None:
    with pytest.raises(ConsolidationError, match="Artículo 2-A"):
        consolidate(BASE, BASE_TEXT, [(AMENDMENT, "Artículo 1.- Solo uno")])


def test_split_parts_uses_spi_j_replacement_and_keeps_wrapped_references() -> None:
    source = RuleSource(
        "spi-j",
        "Texto consolidado",
        "reglamento",
        "Res. base",
        date(2023, 10, 9),
        "https://rules.test/spij.pdf",
    )
    parts = split_parts(
        source,
        """Artículo 1.- La referencia al
Artículo 7 de este reglamento no abre otro artículo.
Artículo 7.- Texto antiguo.
(*) Artículo modificado por el Artículo 2 de la Resolución N° 172-2022-CD/OSIPTEL,
publicada el 8 de octubre de 2022, cuyo texto es el siguiente:
\"Artículo 7.- Texto vigente.
Artículo 8.- Texto anterior.
(*) Artículo modificado por el Artículo 1 de la Resolución Nº 000092-2026-
CD/OSIPTEL, publicada el 15 julio 2026, cuyo texto es el siguiente:
\"Artículo 8.- Texto vigente de condiciones.
Artículo 10.- Texto anterior de reglamento.
(*) Artículo modificado por el Artículo Quinto de la Resolución Nº 172 -2022-CD/ OSIPTEL ,
publicada el 08 octubre 2022, cuyo texto es el siguiente:
\"Artículo 10.- Texto vigente de reglamento.
Artículo 9.- Texto siguiente.""",
    )

    assert parts["Artículo 1"].text.endswith("otro artículo.")
    assert "Texto vigente" in parts["Artículo 7"].text
    assert "Texto antiguo" not in parts["Artículo 7"].text
    assert parts["Artículo 7"].origin.approved_by == "Res. 172-2022-CD/OSIPTEL"
    assert parts["Artículo 7"].origin.text_date == date(2022, 10, 8)
    assert parts["Artículo 8"].text.startswith("Artículo 8.- Texto vigente")
    assert parts["Artículo 8"].origin.approved_by == "Res. 000092-2026-CD/OSIPTEL"
    assert parts["Artículo 8"].origin.text_date == date(2026, 7, 15)
    assert parts["Artículo 10"].text.startswith("Artículo 10.- Texto vigente")
    assert parts["Artículo 10"].origin.approved_by == "Res. 172-2022-CD/OSIPTEL"
    assert parts["Artículo 10"].origin.text_date == date(2022, 10, 8)


def test_lineamientos_keep_their_numbered_labels() -> None:
    source = RuleSource(
        "lineamientos",
        "Lineamientos",
        "lineamiento",
        "Res. 1",
        date(2021, 1, 1),
        "https://rules.test/lineamientos.pdf",
    )

    parts = split_document(
        source,
        """ÍNDICE
2. RECLAMOS CON SUSTENTO EN LA FACTURACIÓN Y COBRO
3. RECLAMOS CON SUSTENTOS DE CALIDAD EN LA PRESTACIÓN DEL SERVICIO

2. RECLAMOS CON SUSTENTO EN LA FACTURACIÓN Y COBRO
1. Nombres y apellidos completos del usuario.
2. Número del documento legal de identificación del usuario.
3. Servicio objeto del reclamo.

3. RECLAMOS CON SUSTENTOS DE CALIDAD EN LA PRESTACIÓN DEL SERVICIO
El usuario puede presentar su reclamo por problemas de calidad.""",
    )

    assert [part.label for part in parts] == ["Numeral 2", "Numeral 3"]
    assert "3. Servicio objeto del reclamo" in parts[0].text


def test_split_document_chunks_long_articles_at_item_boundaries() -> None:
    items = "\n\n".join(
        f"{number}. La infracción se determina conforme al Régimen de Infracciones y "
        "Sanciones aplicable a la presente norma. "
        + "La empresa operadora debe acreditar el cumplimiento de sus obligaciones. "
        * 8
        for number in range(1, 5)
    )

    parts = split_document(
        BASE,
        f"""Artículo 1.- Disposición inicial
Texto inicial.
Artículo 96.- Régimen de Infracciones y Sanciones

{items}""",
    )
    article_96 = [part for part in parts if part.label.startswith("Artículo 96")]

    assert [part.label for part in article_96] == [
        f"Artículo 96 (parte {index} de {len(article_96)})"
        for index in range(1, len(article_96) + 1)
    ]
    assert len(article_96) > 1
    assert all(len(part.text) <= 1200 for part in article_96)
    assert "1. La infracción" in article_96[0].text
    assert "4. La infracción" in " ".join(part.text for part in article_96)


def test_split_parts_replaces_a_modified_item_inside_an_article() -> None:
    source = RuleSource(
        "spi-j-item",
        "Texto consolidado",
        "reglamento",
        "Res. base",
        date(2026, 8, 4),
        "https://rules.test/spij-item.pdf",
    )
    [part] = split_document(
        source,
        """Artículo 1.- Materias.
3. Texto anterior.
(*) Ítem 3 modificado por la Resolución N° 224-2023-CD/OSIPTEL,
publicada el 4 de agosto de 2023, cuyo texto es el siguiente:
\"3. Texto vigente.
4. Otro texto.""",
    )

    assert "Texto vigente" in part.text
    assert "Texto anterior" not in part.text
    assert part.origin.approved_by == "Res. 224-2023-CD/OSIPTEL"


def test_split_parts_normalises_extraction_spacing_and_leading_quotes() -> None:
    [part] = split_document(
        BASE,
        '"Artículo 1.- Prohibiciónde condicionarla al pago previo de una deuda."',
    )

    assert (
        part.text
        == "Artículo 1.- Prohibición de condicionarla al pago previo de una deuda."
    )


def test_split_document_removes_page_footers() -> None:
    [part] = split_document(
        BASE,
        """Artículo 1.- Saldo de tarjeta
La empresa no debe descontar el saldo de la tarjeta
5 | 27
de pago materia de reclamo.""",
    )

    assert "5 | 27" not in part.text
    assert "tarjeta de pago" in part.text


def test_split_document_removes_digital_signature_stamps() -> None:
    precedent = RuleSource(
        "precedent-stamp",
        "Precedente de prueba",
        "precedente",
        "TRASU",
        date(2025, 1, 1),
        "https://rules.test/precedent-stamp.pdf",
    )
    [part] = split_document(
        precedent,
        """SUMILLA: La regla establece Firmado digitalmente por CHAVEZ HUERTAS
David Humberto FAU 20216072155 soft que los precedentes aplican.
Motivo: Doy V° B° Fecha: 14.05.2025 15:28:39 -05:00
1 | 21
conforme a la ley.""",
    )

    assert "Firmado digitalmente" not in part.text
    assert "Motivo:" not in part.text
    assert "Fecha:" not in part.text
    assert "1 | 21" not in part.text
    assert "establece que los precedentes aplican. conforme" in part.text


def test_split_document_excludes_structural_headings_from_articles() -> None:
    parts = split_document(
        BASE,
        """Artículo 1.- Regla anterior.
TÍTULO I: DISPOSICIONES GENERALES
CAPÍTULO I: REGLAS APLICABLES
SUB-CAPÍTULO I: REGLAS ESPECIALES
Artículo 2.- Regla siguiente.""",
    )

    assert [part.label for part in parts] == ["Artículo 1", "Artículo 2"]
    assert all(
        "TÍTULO" not in part.text and "CAPÍTULO" not in part.text for part in parts
    )


def test_split_document_merges_a_short_final_article_piece() -> None:
    first_paragraph = "Texto aplicable. " * 70
    parts = split_document(
        BASE,
        f"""Artículo 1.- Regla extensa
{first_paragraph}

Texto final breve.""",
    )

    assert [part.label for part in parts] == [
        "Artículo 1 (parte 1 de 2)",
        "Artículo 1 (parte 2 de 2)",
    ]
    assert all(200 <= len(part.text) <= 1200 for part in parts)
    assert parts[-1].text.endswith("Texto final breve.")


def test_precedent_drops_the_procedural_opening_before_its_sumilla() -> None:
    precedent = RuleSource(
        "precedent",
        "Precedente de prueba",
        "precedente",
        "TRASU",
        date(2020, 1, 1),
        "https://rules.test/precedent.pdf",
    )

    parts = split_document(
        precedent,
        """RESOLUCIÓN DEL TRIBUNAL
CONSIDERANDO: texto procedimental que no es una regla para visitantes.
SUMILLA: La empresa debe responder el reclamo dentro del plazo.
PRECEDENTE DE OBSERVANCIA OBLIGATORIA: el plazo se cuenta en días hábiles.""",
    )

    assert all("texto procedimental" not in part.text for part in parts)
    assert parts[0].text.startswith("PRECEDENTE DE OBSERVANCIA OBLIGATORIA:")


def test_gazette_precedent_keeps_only_the_osiptel_notice() -> None:
    precedent = RuleSource(
        "gazette",
        "Precedente de prueba",
        "precedente",
        "TRASU",
        date(2006, 1, 19),
        "https://rules.test/gazette.pdf",
        expediente="12957-2005/TRASU/GUS-RA",
        gazette=True,
    )
    parts = split_document(
        precedent,
        """Pág. 312940 El Peruano
Lima, lunes 20 de febrero de 2006
INC
Artículo primero: sanción administrativa.
OSIPTEL
Revocan en parte resolución que declaró infundado reclamo.
RESOLUCIÓN: 2 EXPEDIENTE
N* 12957-2005/TRASU/GUS-RA
En consecuencia, corresponde declarar que ésta constituye un precedente
de observancia obligatoria. La empresa debe sustentar el cobro.
Con la intervención de los señores Vocales.
JUAN CARLOS MEJÍA CORNEJO
Presidente del Tribunal Administrativo de
Solución de Reclamos de Usuarios
SUNARP
TRIBUNAL REGISTRAL
RESOLUCIÓN Nº 021-2006-SUNARP-TR-A
Traslado de Dominio del lote 17.""",
    )

    served = " ".join(part.text for part in parts)
    assert parts[0].text.startswith("corresponde declarar")
    assert "precedente de observancia obligatoria" in served
    assert "La empresa debe sustentar el cobro" in served
    assert "Con la intervención" not in served
    assert "Solución de Reclamos de Usuarios" not in served
    assert "sanción administrativa" not in served
    assert "SUNARP" not in served
    assert "Traslado de Dominio" not in served
    assert "Pág. 312941" not in served
    assert "Lima, martes" not in served


def test_consolidation_rejects_an_amendment_not_later_than_its_base() -> None:
    amendment = RuleSource(
        "old-amendment",
        "Modificatoria antigua",
        "modificatoria",
        "Res. 0",
        date(2022, 1, 1),
        "https://rules.test/old.pdf",
        Changes(modifies=("Artículo 1",)),
        "reglamento",
    )

    with pytest.raises(ConsolidationError, match="not later"):
        consolidate(BASE, BASE_TEXT, [(amendment, AMENDMENT_TEXT)])


def test_rules_sync_consolidates_and_embeds_current_articles(
    database_url: str, tmp_path: Path
) -> None:
    pdfs = {
        BASE.pdf_url: text_pdf([str(line) for line in BASE_TEXT.splitlines()]),
        AMENDMENT.pdf_url: text_pdf(
            [str(line) for line in AMENDMENT_TEXT.splitlines()]
        ),
    }

    async def download(url: str) -> bytes:
        return pdfs[url]

    async def run() -> tuple[dict[str, int], list[Any], int]:
        async with database_pool(database_url, queue_schema="task_queue") as pool:
            embedder = HashingEmbedder()
            counts = await sync(
                pool,
                LocalStore(tmp_path / "pdfs"),
                embedder,
                Redactor.without_ner(),
                sources=(BASE, AMENDMENT),
                download=download,
            )
            repeated = await sync(
                pool,
                LocalStore(tmp_path / "pdfs"),
                embedder,
                Redactor.without_ner(),
                sources=(BASE, AMENDMENT),
                download=download,
            )
            assert repeated == counts
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    "SELECT label, text, text_source FROM rule_passages ORDER BY ordinal"
                )
        return counts, rows, embedder.passages_embedded

    counts, rows, embedded = asyncio.run(run())

    assert counts == {"reglamento": 2}
    assert [row["label"] for row in rows] == ["Artículo 1", "Artículo 2-A"]
    assert "Modificado Texto vigente" in rows[0]["text"]
    assert rows[0]["text_source"] == "Res. 2"
    assert embedded == 2
    assert (tmp_path / "pdfs" / "rules" / "reglamento.pdf").is_file()
