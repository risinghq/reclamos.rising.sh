"""The redactor replaces what identifies a person with a fixed label and keeps
what is public record. `Redactor.without_ner()` exercises the deterministic
layer, so every case here is decided by rules alone."""

import pytest
from reclamos_api.corpus.redact import Redactor

redact = Redactor.without_ner().redact


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("identificado con DNI N.° 09678902", "identificado con DNI N.° [DNI]"),
        ("con DNI 09678902 se acredita", "con DNI [DNI] se acredita"),
        ("documento de identidad N* 44225908", "documento de identidad N* [DNI]"),
        ("la línea 991211111 fue dada de baja", "la línea [TELÉFONO] fue dada de baja"),
        ("teléfono celular 987654321", "teléfono celular [TELÉFONO]"),
        ("al número 976543210", "al número [TELÉFONO]"),
        # A name ends before the prose that follows it.
        (
            "la señora Rocío Bazalar Parra presentó un reclamo por corte",
            "la señora [NOMBRE] presentó un reclamo por corte",
        ),
        # A single-token name after an honorific covers only that token.
        ("el señor Michael vía llamada", "el señor [NOMBRE] vía llamada"),
        (
            "el señor Michael salió de vacaciones",
            "el señor [NOMBRE] salió de vacaciones",
        ),
        ("Señora Milagros acepta usted", "Señora [NOMBRE] acepta usted"),
        (
            "la señorita Vanessa de fecha 01.12.2025",
            "la señorita [NOMBRE] de fecha 01.12.2025",
        ),
        # A call-centre adviser introducing themself is a private person;
        # the operator name after "de" stays.
        (
            "Asesor: señor José, Jovani Gonzales de Win.",
            "Asesor: señor [NOMBRE], [NOMBRE] de Win.",
        ),
        # Staff names after a role cue, a header or a greeting — the cue
        # reaches the name across OCR noise and an intervening qualifier.
        (
            "ejecutivo de atención empresarial Michael MW informó",
            "ejecutivo de atención empresarial [NOMBRE] informó",
        ),
        (
            "ejecutivo de atención empresarial Michael A y",
            "ejecutivo de atención empresarial [NOMBRE] y",
        ),
        (
            "el ejecutivo de atención ¿óbg\nempresarial Michael MW comunica",
            "el ejecutivo de atención ¿óbg\nempresarial [NOMBRE] comunica",
        ),
        (
            "ejecutivo de atención empresarial de la empresa operadora, Michael\nMA. En efecto",
            "ejecutivo de atención empresarial de la empresa operadora, [NOMBRE] En efecto",
        ),
        ("Para: Michael MI O claro.com.pe>", "Para: [NOMBRE] claro.com.pe>"),
        ("funcionario Michael MM indicó", "funcionario [NOMBRE] indicó"),
        ("Para: Michael MI", "Para: [NOMBRE]"),
        ("estimado Michael", "estimado [NOMBRE]"),
        (
            "Buenas tardes estimado Michael,\nEn seguimiento a lo conversado",
            "Buenas tardes estimado [NOMBRE],\nEn seguimiento a lo conversado",
        ),
        (
            "realizadas entre EL RECLAMANTE y la\nasesora comercia! Liliana Vallejos.\n13. De la reproducción",
            "realizadas entre EL RECLAMANTE y la\nasesora comercia! [NOMBRE].\n13. De la reproducción",
        ),
        (
            "servicio telefónico 963-707448, entre el",
            "servicio telefónico [TELÉFONO], entre el",
        ),
        (
            "por la señora Rocío identificada con dozumento de\nidentidad N* 22259274, mediante el cual contrata",
            "por la señora [NOMBRE] identificada con dozumento de\nidentidad N* [DNI], mediante el cual contrata",
        ),
        (
            "identificado con número CID 21552886,",
            "identificado con número CID [CÓDIGO],",
        ),
        (
            "domicilio de la reclamante es Avenida Arequipa 123 Lima, y",
            "domicilio de la reclamante es [DIRECCIÓN], y",
        ),
        (
            "domicilio del usuario se ubica en Jr. Lima 45 Cusco",
            "domicilio del usuario se ubica en [DIRECCIÓN]",
        ),
        (
            "dirección del reclamante es Av. Arequipa 123",
            "dirección del reclamante es [DIRECCIÓN]",
        ),
        (
            "domicilio procesal el Jr. 28 de julio N* 990 en Huanuco.",
            "domicilio procesal el [DIRECCIÓN].",
        ),
        (
            "domicilio de la usuaria es Jr. Lima 45",
            "domicilio de la usuaria es [DIRECCIÓN]",
        ),
        (
            "SERVICIO TELEFÓNICO : 084-984104029",
            "SERVICIO TELEFÓNICO : [TELÉFONO]",
        ),
        ("la línea (084) 984104029", "la línea [TELÉFONO]"),
        # A channel word in nearby prose does not protect a private line.
        (
            "acudió a la oficina de la empresa y su línea 987654321 no funcionaba",
            "acudió a la oficina de la empresa y su línea [TELÉFONO] no funcionaba",
        ),
        (
            "Mediante la web de la empresa, el número 912345678",
            "Mediante la web de la empresa, el número [TELÉFONO]",
        ),
        ("a jort30@hotmail.com", "a [CORREO]"),
        (
            "código de reclamo FC-1206466-2023",
            "código de reclamo [CÓDIGO]",
        ),
        (
            "Código Único de Contrato N° 1155782770",
            "Código Único de Contrato N° [CÓDIGO]",
        ),
        (
            "presentado por la señora Rocío Bazalar Parra",
            "presentado por la señora [NOMBRE]",
        ),
        (
            "el señor Cristian Portugal, asesor de la empresa",
            "el señor [NOMBRE], asesor de la empresa",
        ),
    ],
)
def test_redacts(source: str, expected: str) -> None:
    assert redact(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        # Public record: the vocales who sign, in their signature zone.
        "Con la intervención de los señores Vocales Agnes Franco Templo, "
        "Ignacio Basombrio Zender y Manuel San Román.",
        # Public record: resolution numbers, expedientes, dates, amounts.
        "RESOLUCIÓN N.° 0062389-2023-TRASU/OSIPTEL, EXPEDIENTE N.° "
        "0026410-2023/TRASU/ST-RA, Lima, 13 de octubre de 2023, por S/ 548.00.",
        # Institutional address: OSIPTEL's own seat stays.
        "con sede en Calle De La Prosa 136, San Borja, Lima.",
        "dirección calle uu, distrito",
        "dirección Jr. MN - San Martin",
        # A company name is not a person.
        "contra TELEFÓNICA DEL PERÚ S.A.A. y Entel Perú S.A.",
        # The operator's published channel line is public record.
        "a través de nuestro WhatsApp 999 949 241.",
        # Cue words inside ordinary prose are not staff cues: role words in
        # institutional text, mid-line "para:", and OCR junk fields all keep.
        "LA EMPRESA OPERADORA tenga convenios de Roaming Internacional, no debe",
        "tiene derecho a recibir la información necesaria para:\n\n0) Tomar una decisión",
        "para: (i) Decidir o realizar una elección",
        "validados los datos del\nabonado con el RENIEC mediante el sistema",
        "suspendió el servicio por Uso Indebido, teniendo",
        "de acuerdo al formato contenido en el Anexo N? 2 respectivo.",
        "mediante Memorando N* 00144-TRASU/16 de fecha",
        "desbloquear el equipo Samsung SM-E50 con",
        "del artículo 65* del Reglamento para la Atención de Reclamos",
        "en adelante Directiva;\n\nQue el artículo 42° de la Directiva dispone",
        "reposición de SIM card sin consentimiento",
        "desde el Plan Claro Max 119",
        "RECLAMANTE :\nSERVICIO TELEFÓNICO ; SOS",
        "otras empresas operadoras de la ciudad de Máncora",
    ],
)
def test_keeps(source: str) -> None:
    assert redact(source) == source


def test_reclamante_field_names_the_complainant_everywhere() -> None:
    source = (
        "RECLAMANTE : ROCIO BAZALAR PARRA\n"
        "EMPRESA OPERADORA : TELEFÓNICA DEL PERÚ S.A.A.\n"
        "1. La señora Rocio Bazalar Parra presentó un reclamo."
    )
    out = redact(source)
    assert "Rocio Bazalar Parra" not in out and "ROCIO BAZALAR PARRA" not in out
    assert "TELEFÓNICA DEL PERÚ S.A.A." in out


def test_field_name_with_comma_and_initial_and_single_token() -> None:
    source = (
        "RECLAMANTE : MOYA VALDIVIEZO, ALDO\n"
        "DENUNCIANTE : SMITH HEVERSON ARREDONDO PILCO\n"
        "USUARIO : MARIA\n"
        "1. La usuaria Aldo Moya Valdiviezo indicó. Smith H. también firmó.\n"
        "2. MARIA presentó el pedido.\n"
    )
    out = redact(source)
    for leaked in ("MOYA", "Aldo Moya", "Smith H.", "MARIA"):
        assert leaked not in out, leaked


def test_staff_name_needs_a_cue() -> None:
    for source in (
        "La Gerencia General de Telefónica emitió",
        "El Gerente Comercial de Movistar",
        "El Área Legal de Entel respondió",
        "la Gerencia de Reclamos emitió",
    ):
        assert redact(source) == source


def test_name_span_stops_before_following_prose_with_ner() -> None:
    spacy = pytest.importorskip("spacy")
    redactor = Redactor(spacy.load("es_core_news_sm"))
    out = redactor.redact(
        "La señora Rocío Bazalar Parra presentó un reclamo por corte."
    )
    assert "Rocío Bazalar Parra" not in out
    assert "presentó un reclamo por corte" in out


def test_field_value_never_redacts_institutional_words() -> None:
    source = (
        "RECLAMANTE : JUAN CARLOS PEREZ GOMEZ DE OSIPTEL SERVICIOS PUBLICOS\n"
        "VISTO: el recurso de apelacion, el Tribunal de OSIPTEL resuelve.\n"
        "La EMPRESA OPERADORA ofrece el Plan Premium y el servicio Speedy,\n"
        "del TGS y BCP, en el Procedimiento Administrativo General, y la\n"
        "decision de la usuaria Juan Carlos Perez Gomez es final.\n"
    )
    out = redact(source)
    for kept in (
        "OSIPTEL",
        "Tribunal",
        "EMPRESA OPERADORA",
        "Plan Premium",
        "Speedy",
        "TGS",
        "BCP",
        "Procedimiento Administrativo General",
        "el servicio",
        "de la",
    ):
        assert kept in out, kept
    assert "JUAN CARLOS PEREZ GOMEZ" not in out
    assert "Juan Carlos Perez Gomez" not in out
