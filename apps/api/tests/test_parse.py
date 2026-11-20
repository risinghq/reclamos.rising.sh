from datetime import date

import pytest
from reclamos_api.corpus.parse import parse_resolution

HEADER = """\
TRIBUNAL ADMINISTRATIVO DE SOLUCIÓN DE RECLAMOS DE USUARIOS
{heading}

EXPEDIENTE N?* {expediente}

RESOLUCIÓN FINAL

RESOLUCIÓN N.” {number}

Lima, {day} de {month} de {year}

RECLAMANTE :

EMPRESA OPERADORA : {operator}

SERVICIO : A

{subject_label} : {subject}

CÓDIGO DE RECLAMO : FC-1127071-2023

RESOLUCIÓN DEL TRIBUNAL : {outcome}

VISTO: El expediente de la referencia.
"""


def resolution(**overrides: str) -> str:
    fields = {
        "heading": "RECURSO DE APELACIÓN",
        "expediente": "0024297-2023/TRASU/ST-RA",
        "number": "0060397-2023-TRASU/OSIPTEL",
        "day": "29",
        "month": "setiembre",
        "year": "2023",
        "operator": "TELEFÓNICA DEL PERÚ S.A.A.",
        "subject_label": "MATERIA RECLAMADA",
        "subject": "Cobro por penalidad generado en la Nota de Débito",
        "outcome": "INFUNDADO",
    }
    return HEADER.format(**{**fields, **overrides})


def test_reads_every_field_of_an_appeal() -> None:
    parsed = parse_resolution(resolution())

    assert parsed.missing == []
    assert parsed.number == "0060397-2023-TRASU/OSIPTEL"
    assert parsed.resolved_on == date(2023, 9, 29)
    assert parsed.operator == "TELEFONICA DEL PERU S.A.A."
    assert parsed.appeal_kind == "apelacion"
    assert parsed.subject == "Cobro por penalidad generado en la Nota de Débito"
    assert parsed.claim_type == "billing"
    assert parsed.outcome == "infundado"


def test_reads_a_complaint_against_procedure() -> None:
    parsed = parse_resolution(
        resolution(
            heading="QUEJA",
            expediente="0026151-2023/TRASU/ST-RQJ",
            subject_label="ESCRITO DE QUEJA",
            subject="De fecha 04/10/2023, por la negativa a recibir el reclamo",
            outcome="INFUNDADA",
        )
    )

    assert parsed.missing == []
    assert parsed.appeal_kind == "queja"
    assert parsed.claim_type == "procedural"
    assert parsed.outcome == "infundado"


@pytest.mark.parametrize(
    ("subject", "claim_type"),
    [
        ("Facturación de cargo fijo y venta en cuotas", "billing"),
        ("Contratación no solicitada", "unrequested_contract"),
        ("Renovación no solicitada", "unrequested_contract"),
        ("Falta de servicio (baja injustificada)", "service_cut"),
        ("Calidad en la prestación del servicio de internet fijo", "service_quality"),
        ("Problemas con la portabilidad numérica", "porting"),
        ("Incumplimiento de ofertas y promociones", "contract_terms"),
    ],
)
def test_classifies_the_subject(subject: str, claim_type: str) -> None:
    assert parse_resolution(resolution(subject=subject)).claim_type == claim_type


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("FUNDADO", "fundado"),
        ("FUNDADA", "fundado"),
        ("INFUNDADO", "infundado"),
        ("IMPROCEDENTE", "improcedente"),
        ("FUNDADO EN PARTE", "fundado_en_parte"),
        ("INFUNDAD0", "infundado"),
        (
            (
                "IMPROCEDENTE: Queja por falta de respuesta al reclamo\n"
                "FUNDADA: la queja cuando la empresa no aplica el silencio"
            ),
            "mixto",
        ),
    ],
)
def test_normalizes_the_outcome(outcome: str, expected: str) -> None:
    assert parse_resolution(resolution(outcome=outcome)).outcome == expected


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        ("ÓNICA DEL PERÚ S.A.A.", "TELEFONICA DEL PERU S.A.A."),
        ("TELEFONICA DEL PERU S.A.A. 33% E", "TELEFONICA DEL PERU S.A.A."),
        ("TELEFÓNICA DEL PERÚ SAA.", "TELEFONICA DEL PERU S.A.A."),
        ("ENTELPERUSA. e E E", "ENTEL PERU S.A."),
        ("WOWTELSA.C. SS PS", "WOW TEL S.A.C."),
        ("AMÉRICA MÓVIL PERÚ S.A.C. 5% 55", "AMERICA MOVIL PERU S.A.C."),
        ("WI-NET TELECOM S.A.C.", "WIN NET - TELECOM S.A.C."),
        ("Nueva Red Móvil S.A.C.", "NUEVA RED MOVIL S.A.C."),
    ],
)
def test_reads_the_operator_through_scan_noise(operator: str, expected: str) -> None:
    assert parse_resolution(resolution(operator=operator)).operator == expected


def test_an_unreadable_operator_fails_instead_of_guessing() -> None:
    parsed = parse_resolution(resolution(operator="Sada\nPERU S.A."))

    assert parsed.operator is None
    assert parsed.missing == ["operator"]


def test_names_what_is_missing() -> None:
    parsed = parse_resolution(resolution(subject="Un asunto sin clasificar"))

    assert parsed.number
    assert parsed.claim_type is None
    assert parsed.missing == ["claim_type"]
    assert parsed.detail() == "missing: claim_type"


def test_a_text_without_a_header_misses_everything() -> None:
    parsed = parse_resolution("Contrato de arrendamiento entre las partes.")

    assert parsed.missing == [
        "date",
        "operator",
        "kind",
        "subject",
        "claim_type",
        "outcome",
    ]


def test_reads_the_labels_of_2026_resolutions() -> None:
    text = resolution(
        operator="INTEGRATEL PERU S.A.A. (ANTES TELEFÓNICA DEL\nPERÚ S.A.A.)",
        subject_label="CONCEPTO CUESTIONADO",
        subject="Incumplimiento en la renovación del equipo",
    ).replace("RESOLUCIÓN DEL TRIBUNAL", "SENTIDO DE LA RESOLUCIÓN")

    parsed = parse_resolution(text)

    assert parsed.missing == []
    assert parsed.operator == "INTEGRATEL PERU S.A.A."
    assert parsed.claim_type == "equipment"
    assert parsed.outcome == "infundado"


def test_the_operator_on_the_page_wins_over_the_scan() -> None:
    parsed = parse_resolution(
        resolution(operator="A."), summary="Empresa: ENTEL PERÚ S.A.\nSumilla: x"
    )

    assert parsed.operator == "ENTEL PERU S.A."


def test_the_page_summary_gives_the_outcome_when_the_scan_lost_its_label() -> None:
    text = resolution(
        heading="QUEJA",
        expediente="0007510-2024/TRASU/ST-RQJ",
        subject_label="SERVICIO",
        subject="MO EE",
        outcome="",
    ).replace("RESOLUCIÓN DEL TRIBUNAL", "RESOLUCIÓN DEL")

    parsed = parse_resolution(
        text, summary="Sumilla: Declaran\nFUNDADA\nla queja por silencio positivo"
    )

    assert parsed.missing == []
    assert parsed.outcome == "fundado"
    assert parsed.claim_type == "procedural"


def test_a_resolution_that_voids_a_step_has_no_claim_to_classify() -> None:
    parsed = parse_resolution(
        resolution(
            subject_label="OBSERVACIÓN",
            subject="",
            outcome="DEJAR SIN EFECTO LA ELEVACIÓN DEL EXPEDIENTE",
        )
    )

    assert parsed.outcome == "sin_efecto"
    assert parsed.claim_type == "procedural"
    assert parsed.missing == []


# Resolutions before 2020 print no full number, spell the date out and label the
# subject `CONCEPTOS RECLAMADOS`. Each text is an excerpt of a real scan.
SCAN_2006 = """\
S>OSIPTEL S
RESOLUCIÓN: 1 EXPEDIENTE N* 12323-2006/TRASU/GUS-RA |
o l RECURSO DE APELACION bla pa Enri i
Lima, catorce de noviembre del dos mil seis |
CONCEPTOS RECLAMADOS : Cargo fijo del Plan Súper Control 55 en el recibo de
julio de dos mil seis.
CICLO DE FACTURACIÓN : 20
( o EMPRESA OPERADORA : AMERICA MOVIL PERU S.A.C. : i
o “| NUMERO'DE RECLAMO : 0000042652 : > : : a es
RESOLUCIÓN DE EMPRESA : Carta GCC/BOCLG-R-11355-06
. OPERADORA
RESOLUCIÓN DEL TRIBUNAL : FUNDADO úl
VISTO : El expediente de la referencia.
"""

SCAN_2016_COLUMNS = """\
EXPEDIENTE No 16733-2016lTRASUlST-RQJ
QUEJA
Lima, 4 de Agosto del 2016

RECLAMANTE

EMPRESA OPERADORA
REFERENCIA
                                                         : VIETTEL PERU S.A.C.

                                                         : Carta No RQ-00398-16 de fecha 09 de junio de
ESCRITO DE QUEJA                                          De fecha 06 de junio de 2016, por no permitir la
                                                          presentación de una queja.

RESOLUCIÓN DEL TRIBUNAL                                  : INFUNDADA
VISTO: El expediente de la referencia.
"""


def test_reads_a_resolution_from_before_2020() -> None:
    parsed = parse_resolution(SCAN_2006)

    assert parsed.missing == []
    assert parsed.number is None
    assert parsed.resolved_on == date(2006, 11, 14)
    assert parsed.operator == "AMERICA MOVIL PERU S.A.C."
    assert parsed.appeal_kind == "apelacion"
    assert parsed.claim_type == "billing"
    assert parsed.outcome == "fundado"


def test_reads_a_complaint_whose_scan_put_the_values_after_the_labels() -> None:
    parsed = parse_resolution(SCAN_2016_COLUMNS)

    assert parsed.missing == []
    assert parsed.resolved_on == date(2016, 8, 4)
    assert parsed.operator == "VIETTEL PERU S.A.C."
    assert parsed.appeal_kind == "queja"
    assert parsed.claim_type == "procedural"
    assert parsed.outcome == "infundado"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Lima, uno de febrero de dos mil siete.", date(2007, 2, 1)),
        ("Lima, veintidós de noviembre del dos mil cinco.", date(2005, 11, 22)),
        ("Lima, treinta y uno de enero de dos mil nueve", date(2009, 1, 31)),
        ("Lima, 30 de diciembre del año dos mil tres.", date(2003, 12, 30)),
        ("Lima, 29 de diciembre det 2017", date(2017, 12, 29)),
        ("Lima, 26 de junio dal 2018 Ñ", date(2018, 6, 26)),
        ("Lima. 25 de marzo de 2014", date(2014, 3, 25)),
        ("Lima, 31 de febrero de 2020", None),
    ],
)
def test_reads_a_date_spelled_in_words_or_misread(
    line: str, expected: date | None
) -> None:
    assert parse_resolution(f"RECURSO DE APELACION\n{line}\n").resolved_on == expected


def test_the_page_summary_fills_what_the_scan_lost() -> None:
    scan = SCAN_2006.replace("RESOLUCIÓN DEL TRIBUNAL : FUNDADO úl", "").replace(
        "CONCEPTOS RECLAMADOS :", "XXXX :"
    )
    summary = (
        "Sumilla: Declaran\nfundada\nla Apelación por la facturación del cargo fijo."
    )

    parsed = parse_resolution(scan, summary=summary)

    assert parsed.outcome == "fundado"
    assert parsed.claim_type == "billing"


@pytest.mark.parametrize(
    ("summary", "outcome"),
    [
        ("Sumilla: Declaran INFUNDADO el recurso", "infundado"),
        ("Sumilla: Declaran\nparcialmente\nfundado\nel recurso", "fundado_en_parte"),
        ("Sumilla: Declaran improcedente Queja en la cual", "improcedente"),
        ("Se declara\nFUNDADA\nla queja por silencio", "fundado"),
    ],
)
def test_reads_the_ruling_the_page_summary_states(summary: str, outcome: str) -> None:
    assert parse_resolution("sin cabecera", summary=summary).outcome == outcome


JARU_QUEJA = """\
RESOLUCIÓN DE LA SALA UNIPERSONAL 1
JUNTA DE APELACIONES DE RECLAMOS DE USUARIOS
ORGANISMO SUPERVISOR DE LA INVERSIÓN
EN ENERGÍA Y MINERÍA
OSINERGMIN N* 13425-2021-OS/JARU-S1
Lima, 27 de octubre del 2021
Expediente: N* 202100215314
Concesionaria: Gas Natural de Lima y Callao S.A. Cálidda
Materia: Queja por facturar deuda materia de reclamo, por no elevar expediente
de apelación y por corte de servicio estando en reclamo
Suministro: |
SUMILLA: La queja por facturar deuda materia de reclamo es fundada cuando la
concesionaria no acreditó que no incluyó indebidamente el importe reclamado en
un recibo.
SE RESUELVE:
Artículo 1". - DECLARAR FUNDADA la queja por facturar deuda materia de reclamo.
"""

JARU_APPEAL_2021 = """\
RESOLUCIÓN DE LA SALA UNIPERSONAL 2
JUNTA DE APELACIONES DE RECLAMOS DE USUARIOS
ORGANISMO SUPERVISOR DE LA INVERSIÓN
EN ENERGÍA Y MINERÍA
OSINERGMIN N? 4-2021 OS/JARU-S2
Lima, 05 de enero del 2021
Expediente N* 202000171329
Usuario: MS
Materia: Excesivos consumos facturados
Resolución impugnada: N* GNLC-RES-12681-2020
SUMILLA: La empresa distribuidora deberá refacturar los consumos de abril,
mayo y junio de 2020, así como los cargos asociados a estos.
1. ANTECEDENTES
1.3. 10 de noviembre de 2020.- La recurrente presentó recurso de apelación
contra la Resolución N* GNLC-RES-12681-2020.
SE RESUELVE:
Artículo 1".- DECLARAR FUNDADO el recurso de apelación.
"""


def test_reads_a_jaru_queja() -> None:
    parsed = parse_resolution(
        JARU_QUEJA,
        summary="Resolución referida a una queja administrativa presentada por "
        "usuario del servicio de gas natural",
        sector="energy",
    )

    assert parsed.missing == []
    assert parsed.number == "13425-2021-OS/JARU-S1"
    assert parsed.resolved_on == date(2021, 10, 27)
    assert parsed.operator == "GAS NATURAL DE LIMA Y CALLAO S.A."
    assert parsed.appeal_kind == "queja"
    assert parsed.claim_type == "procedural"
    assert parsed.outcome == "fundado"


def test_reads_a_jaru_appeal_and_the_company_from_the_impugnada_code() -> None:
    parsed = parse_resolution(JARU_APPEAL_2021, sector="energy")

    assert parsed.missing == []
    assert parsed.number == "4-2021-OS/JARU-S2"
    assert parsed.resolved_on == date(2021, 1, 5)
    assert parsed.operator == "GAS NATURAL DE LIMA Y CALLAO S.A."
    assert parsed.appeal_kind == "apelacion"
    assert parsed.subject == "Excesivos consumos facturados"
    assert parsed.claim_type == "billing"
    assert parsed.outcome == "fundado"


@pytest.mark.parametrize("code", ["GC-RES-306050-2018", "SEAL-RES-123-2018"])
def test_a_company_code_quoted_for_another_case_is_not_the_operator(
    code: str,
) -> None:
    body = (
        JARU_APPEAL_2021.replace(
            "Resolución impugnada: N* GNLC-RES-12681-2020", ""
        ).replace(
            "contra la Resolución N* GNLC-RES-12681-2020.",
            "contra la resolución impugnada.",
        )
        + f"\n2 En la Resolución N* {code} este Tribunal resolvió "
        "un caso distinto."
    )

    parsed = parse_resolution(body, sector="energy")

    assert parsed.operator is None
    assert "operator" in parsed.missing


def test_an_appeal_whose_antecedents_mention_a_queja_stays_an_appeal() -> None:
    body = JARU_APPEAL_2021.replace(
        "1.3. 10 de noviembre de 2020.- La recurrente presentó recurso de apelación",
        "1.3. 12 de octubre de 2020.- El usuario presentó queja por aplicación "
        "de silencio administrativo positivo.\n"
        "1.4. 10 de noviembre de 2020.- La recurrente presentó recurso de "
        "apelación",
    )

    parsed = parse_resolution(body, sector="energy")

    assert parsed.appeal_kind == "apelacion"
    assert parsed.claim_type == "billing"


def test_reads_a_queja_named_on_the_materia_line_in_quotes() -> None:
    body = JARU_QUEJA.replace(
        "Materia: Queja por facturar deuda materia de reclamo, por no elevar "
        "expediente\nde apelación y por corte de servicio estando en reclamo",
        "Materia: “Queja”",
    )

    parsed = parse_resolution(body, sector="energy")

    assert parsed.appeal_kind == "queja"
    assert parsed.claim_type == "procedural"


def test_reads_the_operator_named_after_contra() -> None:
    parsed = parse_resolution(
        JARU_APPEAL_2021.replace(
            "Resolución impugnada: N* GNLC-RES-12681-2020",
            "VISTOS: Los expedientes, referidos a los procedimientos de reclamo "
            "seguidos por Productos Forma S.A.* contra Enel Distribución Perú "
            "S.A.A.",
        ),
        sector="energy",
    )

    assert parsed.operator == "ENEL DISTRIBUCION PERU S.A.A."


@pytest.mark.parametrize(
    ("ruling", "outcome"),
    [
        ("Declarar que CARECE DE OBJETO emitir pronunciamiento", "sin_efecto"),
        ("DESESTIMAR el recurso de apelación", "sin_efecto"),
        ("Declarar IMPROCEDENTE por extemporáneo el recurso", "improcedente"),
        ("ACUMULAR los procedimientos de reclamo signados", "sin_efecto"),
        ("SUSPENDER el procedimiento para recabar información", "sin_efecto"),
        ("RECTIFICAR el nombre de la Resolución N* 8765-2021", "sin_efecto"),
    ],
)
def test_reads_a_procedural_ruling(ruling: str, outcome: str) -> None:
    body = JARU_APPEAL_2021.replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        f"Artículo Único.- {ruling}.",
    ).replace("Materia: Excesivos consumos facturados", "Materia: Medida cautelar")

    parsed = parse_resolution(body, sector="energy")

    assert parsed.outcome == outcome
    assert parsed.claim_type == "procedural"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Lima,02 de enero de 2019", date(2019, 1, 2)),
        ("Lima, 27 de octubre\ndel 2021", date(2021, 10, 27)),
        ("Lima, 20 de\ndiciembre del 2021", date(2021, 12, 20)),
        ("Lima, 23 de enero 2019", date(2019, 1, 23)),
    ],
)
def test_reads_a_jaru_date_the_scan_broke_up(line: str, expected: date) -> None:
    body = JARU_APPEAL_2021.replace("Lima, 05 de enero del 2021", line)

    assert parse_resolution(body, sector="energy").resolved_on == expected


@pytest.mark.parametrize(
    ("ruling", "outcome"),
    [
        (
            "REVOCAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "INFUNDADO el reclamo del recurrente y, en consecuencia, "
            "declararlo FUNDADO",
            "fundado",
        ),
        (
            "REVOCAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "INFUNDADO el reclamo del recurrente y, en consecuencia, "
            "declararlo IMPROCEDENTE",
            "improcedente",
        ),
        (
            "REVOCAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "FUNDADO EN PARTE el reclamo del recurrente y, en consecuencia, "
            "declararlo FUNDADO",
            "fundado",
        ),
        (
            "REVOCAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "el reclamo FUNDADO EN PARTE y, en consecuencia, declararlo "
            "FUNDADO",
            "fundado",
        ),
        (
            "REVOCAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "el reclamo INFUNDADO y, en consecuencia, declararlo FUNDADO",
            "fundado",
        ),
        (
            "CONFIRMAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "INFUNDADO el reclamo del recurrente",
            "infundado",
        ),
        (
            "CONFIRMAR la Resolución N* GNLC-RES-06541-2021 que declaró "
            "FUNDADO EN PARTE el reclamo del recurrente",
            "fundado_en_parte",
        ),
        (
            "Declarar NULA la Resolución N* GNLC-RES-06541-2021 y LO ACTUADO; "
            "y declarar FUNDADO el reclamo por el silencio administrativo "
            "positivo",
            "fundado",
        ),
        (
            "Declarar FUNDADO el reclamo de la recurrente.\n\n"
            '2 "37.2 La queja será declarada improcedente cuando el '
            "procedimiento de reclamo haya concluido",
            "fundado",
        ),
    ],
)
def test_reads_the_verdict_the_jaru_declares(ruling: str, outcome: str) -> None:
    body = JARU_APPEAL_2021.replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        f"Artículo 1.- {ruling}.",
    )

    assert parse_resolution(body, sector="energy").outcome == outcome


def test_considerations_are_not_the_ruling() -> None:
    body = JARU_APPEAL_2021.replace("SE RESUELVE:\n", "").replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        "Considerando que se debe acumular pagos y es extemporáneo.\n"
        "Artículo 1.- REVOCAR la resolución impugnada.",
    )

    parsed = parse_resolution(body, sector="energy")

    assert parsed.outcome is None
    assert "outcome" in parsed.missing
    assert parsed.claim_type == "billing"


def test_footnotes_before_the_articles_do_not_hide_the_ruling() -> None:
    body = JARU_APPEAL_2021.replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        "1 Aprobada por Resolución N? 269-2014-0S/CD.\n\n"
        '2 "37.2 La queja será declarada improcedente cuando el procedimiento '
        "de reclamo haya concluido o no subsista el\n\n"
        'defecto de tramitación materia de queja (...)".\n\n'
        "3 Aprobado por Resolución N* 044-2018-0S/CD.\n\n"
        "RESOLUCIÓN DE LA SALA UNIPERSONAL 1\n"
        "Artículo Único. - Declarar IMPROCEDENTE la queja por corte de "
        "servicio estando en\nreclamo.\nFirmado Digitalmente",
    )

    assert parse_resolution(body, sector="energy").outcome == "improcedente"


@pytest.mark.parametrize(
    "mention",
    [
        "el levantamiento de observaciones",
        "la acumulación de pagos",
        "la desestimación del recurso",
    ],
)
def test_a_noun_in_an_article_is_not_a_disposition(mention: str) -> None:
    body = JARU_APPEAL_2021.replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        f"Artículo 1.- REVOCAR la resolución impugnada y ordenar {mention}.",
    )

    parsed = parse_resolution(body, sector="energy")

    assert parsed.outcome is None
    assert "outcome" in parsed.missing


def test_a_footnote_is_not_a_ruling() -> None:
    body = JARU_APPEAL_2021.replace(
        'Artículo 1".- DECLARAR FUNDADO el recurso de apelación.',
        "Artículo 1.- REVOCAR la resolución impugnada.",
    ) + ("\n3 El levantamiento de observaciones y la acumulación de pagos.")

    parsed = parse_resolution(body, sector="energy")

    assert parsed.outcome is None
    assert "outcome" in parsed.missing


def test_reads_the_ruling_before_the_footnotes() -> None:
    body = JARU_APPEAL_2021 + (
        "\n2 Aprobado por Resolución N* 044-2018-OS/CD.\n"
        "Artículo 1162.- El Margen Comercial se basará en una gestión "
        "comercial eficiente."
    )

    assert parse_resolution(body, sector="energy").outcome == "fundado"
