"""Read what a TRASU or JARU resolution states from its text.

Every resolution opens with a block of labelled lines (expediente, resolution
number, date, operator, subject, outcome); the labels differ by sector. The
text comes from OCR for scanned PDFs, so the patterns tolerate dropped accents,
stray punctuation and misread characters in the labels.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher, get_close_matches

HEADER_CHARS = 3500
TAIL_CHARS = 8000

MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

# `PARSER_VERSION` marks what filled the parsed fields: a change to the
# parser bumps it so a crawl re-parses the rows an older parser read.
PARSER_VERSION = "2"

# These labels end the value of the preceding field.
_LABELS = (
    r"RECLAMANTE|RECURRENTE|SERVICIO|EMPRESA(?:\s+(?:OPERADORA|DISTRIBUIDORA|"
    r"CONCESIONARIA|LICENCIATARIA))?|CONCESIONARIA|MATERIAS?(?:\s+RECLAMADA)?|"
    r"CONCEPTOS?\s+(?:RECLAMADOS?|CUESTIONADOS?)|ESCRITO\s+DE\s+QUEJA|C.DIGO\s+DE\s+RECLAMO|"
    r"RESOLUCI.N\s+(?:IMPUGNADA|DE\s+(?:LA\s+)?EMPRESA|DEL\s+TRIBUNAL|DEL\s+TRASU)|"
    r"SENTIDO\s+DE\s+LA\s+RESOLUCI.N|N.MERO\s+DE\s+(?:SERVICIO|RECLAMO|SUMINISTRO)|"
    r"SUMINISTRO|UBICACI.N|MONTO|"
    r"CICLO\s+DE\s+FACTURACI.N|SUMILLA|"
    r"REFERENCIA|RECLAMO\s+EN\s+.{1,4}\s+INSTANCIA|VISTO|ANTECEDENTES"
)

# A scan leaves a stray mark, a border or one or two characters before a label.
_NOISE = r"[ \t]*(?:(?:[^\W_]{1,2}[ \t]+|[^\w\s]{1,3}[ \t]*)){0,3}"
_DASHES = "\N{EN DASH}\N{EM DASH}"

# Operators whose names scans often damage. A name that is close to one of
# these takes the spelling here; any other name is kept as printed.
KNOWN_OPERATORS = (
    "AMERICA MOVIL PERU S.A.C.",
    "ENTEL PERU S.A.",
    "INTEGRATEL PERU S.A.A.",
    "TELEFONICA DEL PERU S.A.A.",
    "TELEFONICA MOVILES S.A.",
    "NEXTEL DEL PERU S.A.",
    "AMERICATEL PERU S.A.",
    "TELMEX PERU S.A.",
    "VIETTEL PERU S.A.C.",
    "WIN NET - TELECOM S.A.C.",
    "WOW TEL S.A.C.",
)

# The electricity distributors, gas distributors and concessionaires a JARU
# resolution names as `Empresa`. A renamed company stays two operators, as the
# corpus keeps Telefónica and Integratel apart: JARU texts print both Enel
# Distribución Perú and Pluz Energía Perú.
ENERGY_OPERATORS = (
    "LUZ DEL SUR S.A.A.",
    "ENEL DISTRIBUCION PERU S.A.A.",
    "PLUZ ENERGIA PERU S.A.A.",
    "HIDRANDINA S.A.A.",
    "ELECTRO CENTRO S.A.",
    "ELECTRO NOROESTE S.A.",
    "ELECTRO NORTE S.A.",
    "ELECTRO ORIENTE S.A.",
    "ELECTRO SUR ESTE S.A.",
    "ELECTRO SUR S.A.",
    "ELECTRO PUNO S.A.A.",
    "ELECTRO UCAYALI S.A.",
    "ELECTRO DUNAS S.A.A.",
    "SOCIEDAD ELECTRICA DE AREQUIPA S.A.",
    "ELECTROPERU S.A.",
    "EMPRESA DE TRANSMISION ELECTRICA CENTRO NORTE S.A.",
    "EMPRESA ELECTRICA DE PIURA S.A.",
    "EMPRESA MUNICIPAL DE SERVICIO ELECTRICO DE YAULI S.A.",
    "EMPRESA MUNICIPAL DE SERVICIOS ELECTRICOS UTCUBAMBA S.A.",
    "ADINELSA S.A.",
    "COELVISA S.A.",
    "EDECANETE S.A.",
    "EDEGEL S.A.A.",
    "EDELSA S.A.",
    "EGEMSA S.A.",
    "EILHICHA S.A.",
    "ELECTRO PANGOA S.A.",
    "ELECTRO TOCACHE S.A.",
    "GAS NATURAL DE LIMA Y CALLAO S.A.",
    "GASES DEL PACIFICO S.A.C.",
    "CONTUGAS S.A.C.",
)

_ENERGY_NUMBER = re.compile(
    r"(\d{1,6})\s*-\s*(\d{4})\s*[- ]?\s*OS\s*/\s*JARU\s*[-\u2013/]\s*(S\w+)",
    re.IGNORECASE,
)
# A JARU expediente is the twelve-digit file number.
_ENERGY_EXPEDIENTE = re.compile(r"EXPEDIENTE\s*N?[°º.]?\s*(\d{12})", re.IGNORECASE)
# The resolutive articles sit at the end of the resolution.
_RULING_WORDS = re.compile(
    r"\b(FUNDAD[OA]S?|INFUNDAD[OA]S?|IMPROCEDENTE|NUL[OA]S?|NULIDAD)\b", re.IGNORECASE
)
# A ruling written as a disposition, not a verdict word. `CARECE DE OBJETO` and
# `DESESTIMAR` dismiss the appeal; `ACUMULAR`, `SUSPENDER`, `RECTIFICAR`,
# `ESTÉSE` and `LEVANTAR` end or move the procedure without ruling a claim.
# Only verb inflections match: the nouns (`acumulación`, `desestimación`,
# `levantamiento`, `rectificación`) are excluded, since an article can quote
# them without ordering anything.
_PROCEDURAL_DISMISSAL = re.compile(
    r"CARECE\s+DE\s+OBJETO|DESESTIMA(?!CI[OÓ]N|TORI)\w*|EXTEMPOR[AÁ]NE[OA]S?\b"
    r"|INADMISIBLES?\b",
    re.IGNORECASE,
)
_PROCEDURAL_RULING = re.compile(
    r"\b(ACUMULA(?!CI[OÓ]N|MIENTO)\w*|SUSPEND\w*|RECTIFICA(?!CI[OÓ]N)\w*"
    r"|LEVANTA(?!MIENTO)\w*|EST[EÉ]SE)\b",
    re.IGNORECASE,
)
# The resolutive section anchors on `SE RESUELVE`/`POR LO TANTO`; when none
# prints, the `Artículo 1` heading is the fallback — matched with its `.`/`-`
# so a footnote's `Artículo 1162` cannot be the anchor.
_ARTICLE_ONE = re.compile(r"art[íi]culo\s+1\s*[°º*”\"'“”]?\s*[.\-]", re.IGNORECASE)
_ARTICLE_LINE = re.compile(r"^\s*art[íi]culo\b", re.IGNORECASE)
_SIGNATURE = re.compile(r"^\s*(firmado|reg[íi]strese)", re.IGNORECASE)
# The resolution code of the first instance names the company that issued it,
# which is the only place the operator appears in resolutions that print no
# `Empresa`/`Concesionaria` label. Only prefixes that the labeled rows
# themselves confirm are mapped: `GC` matched Hidrandina cases more often
# than Electro Dunas, and `SGGC` and `SEL` stay unconfirmed.
_IMPUGNADA = re.compile(
    r"[Ii]mpugnada\s*[:\-]?\s*(?:N\s*[°º\*\.“”\"]*\s*)?"
    r"([A-ZÁÉÍÓÚÑ]{2,10})\s*[-/]"
)
IMPUGNADA_OPERATORS = {
    "GNLC": "GAS NATURAL DE LIMA Y CALLAO S.A.",
    "GLNC": "GAS NATURAL DE LIMA Y CALLAO S.A.",
    "DRR": "LUZ DEL SUR S.A.A.",
    "SGSC": "LUZ DEL SUR S.A.A.",
    "SEAL": "SOCIEDAD ELECTRICA DEL SUR OESTE S.A.",
    "GZT": "ELECTRO SUR S.A.",
    "CQ": "ELECTRO SUR ESTE S.A.",
}
# A `NULA` sends the file back to the company without ruling on a claim, like
# the Tribunal's `sin efecto`.
_VERDICTS = {
    "fundado": "fundado",
    "fundada": "fundado",
    "infundado": "infundado",
    "infundada": "infundado",
    "improcedente": "improcedente",
    "nulo": "sin_efecto",
    "nula": "sin_efecto",
    "nulidad": "sin_efecto",
}

# What the `Materia` of a JARU resolution claims. The order puts the narrow,
# unambiguous topics before the broad ones, as CLAIM_TYPES does.
ENERGY_CLAIM_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("meter", ("medidor",)),
    ("recupero", ("recupero",)),
    (
        "connection",
        (
            "conexion",
            "acometida",
            "suministro nuevo",
            "nuevo suministro",
            "punto de suministro",
            "factibilidad",
            "instalacion",
            "habilitacion",
            "viabilidad",
            "reubicacion",
            "reposicion",
            "electrificacion",
        ),
    ),
    (
        "service_cut",
        ("corte", "suspension", "reconexion", "baja del suministro", "retiro"),
    ),
    (
        "service_quality",
        ("calidad", "tension", "voltaje", "interrupcion", "deficiencia del servicio"),
    ),
    (
        "billing",
        (
            "factur",
            "cobro",
            "recibo",
            "monto",
            "deuda",
            "pago",
            "tarifa",
            "cargo",
            "saldo",
        ),
    ),
    ("consumption", ("lectura", "consumo", "estimad")),
    (
        "contract_terms",
        ("contrato", "condiciones contractuales", "clausula", "titularidad"),
    ),
)

_NUMBER = re.compile(
    r"(\d{6,8})\s*-\s*(\d{4})\s*-\s*TRASU\s*/\s*OSIPTEL", re.IGNORECASE
)
_EXPEDIENTE = re.compile(
    r"\d{4,8}\s*-\s*\d{4}\s*.?\s*TRASU\s*[/lI|]?\s*(?:ST|GUS)?\s*[-/lI|]?\s*(RA|RQJ)\b",
    re.IGNORECASE,
)
# The date line, as `Lima, 14 de noviembre del 2017` or, in older resolutions,
# `Lima, catorce de noviembre del dos mil seis`. `del` is often misread.
_DATE = re.compile(
    r"Lima[,.]?[ \t]*([^\W_][\w ]{0,20}?)\s+de\s+([^\W\d_]+?)\s+"
    r"(?:d[^\W\d_]{1,2}\s+)?(?:año\s+)?([^\n]{3,40})",
    re.IGNORECASE,
)
_UNIT_WORDS = (
    *("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho"),
    *("nueve", "diez", "once", "doce", "trece", "catorce", "quince", "dieciseis"),
    *("diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidos"),
    *("veintitres", "veinticuatro", "veinticinco", "veintiseis", "veintisiete"),
    *("veintiocho", "veintinueve"),
)
_UNITS = {word: number for number, word in enumerate(_UNIT_WORDS)} | {"primero": 1}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50}
_LEGAL_SUFFIX = re.compile(r"\b(?:S\.A\.A|S\.A\.C|S\.A|S\.R\.L|E\.I\.R\.L)\b\.?")

# The first group whose keywords appear in the subject wins, so the order puts
# the narrow, unambiguous topics before the broad ones.
CLAIM_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unrequested_contract", ("no solicitad",)),
    ("porting", ("portabilidad", "cambio de operador")),
    (
        "service_cut",
        (
            "suspension",
            "baja",
            "corte",
            "falta de servicio",
            "reconexion",
            "cancelacion",
        ),
    ),
    (
        "service_quality",
        (
            "calidad",
            "velocidad",
            "averia",
            "interrupcion",
            "intermitencia",
            "instalacion",
            "traslado",
            "reparacion",
        ),
    ),
    (
        "billing",
        (
            "factur",
            "cobro",
            "recibo",
            "tarifa",
            "consumo",
            "cargo",
            "monto",
            "pago",
            "deuda",
            "penalidad",
            "saldo",
        ),
    ),
    ("equipment", ("equipo", "terminal", "garantia")),
    (
        "contract_terms",
        (
            "condiciones contractuales",
            "oferta",
            "promocion",
            "contrato",
            "plan tarifario",
        ),
    ),
)


@dataclass(slots=True)
class Parsed:
    number: str | None = None
    resolved_on: date | None = None
    operator: str | None = None
    subject: str | None = None
    claim_type: str | None = None
    appeal_kind: str | None = None
    outcome: str | None = None
    missing: list[str] = field(default_factory=list)

    def detail(self) -> str:
        return "missing: " + ", ".join(self.missing)


def parse_resolution(
    body: str, *, summary: str = "", sector: str = "telecom"
) -> Parsed:
    if sector == "energy":
        return _parse_energy(body, summary=summary)
    header = body[:HEADER_CHARS]
    parsed = Parsed(
        number=_number(header),
        resolved_on=_date(header),
        operator=_operator(header, summary),
        appeal_kind=_appeal_kind(header),
    )
    parsed.subject = _subject(header)
    parsed.outcome = _outcome(header) or _ruling_in(summary) or _sumilla_ruling(summary)
    if parsed.appeal_kind is None:
        parsed.appeal_kind = _sumilla_kind(summary)
    if parsed.outcome == "sin_efecto":
        # The Tribunal sent the file back to the operator without ruling on a claim.
        parsed.claim_type = "procedural"
    else:
        parsed.claim_type = claim_type(
            parsed.subject or "", appeal_kind=parsed.appeal_kind
        ) or claim_type(_sumilla_topic(summary), appeal_kind=parsed.appeal_kind)

    checks = (
        ("date", parsed.resolved_on),
        ("operator", parsed.operator),
        ("kind", parsed.appeal_kind),
        ("subject", parsed.subject or parsed.claim_type),
        ("claim_type", parsed.claim_type),
        ("outcome", parsed.outcome),
    )
    parsed.missing = [name for name, value in checks if value is None]
    return parsed


def claim_type(
    subject: str,
    *,
    appeal_kind: str | None,
    types: tuple[tuple[str, tuple[str, ...]], ...] = CLAIM_TYPES,
) -> str | None:
    if appeal_kind == "queja":
        return "procedural"
    text = _plain(subject).lower()
    for name, keywords in types:
        if any(re.search(rf"\b{keyword}", text) for keyword in keywords):
            return name
    return None


def _parse_energy(body: str, *, summary: str = "") -> Parsed:
    """A JARU resolution's fields. Most JARU files are a user's appeal in
    second instance; the rest are a `queja` on the procedure itself or a
    procedural ruling (an acumulación, a cautelar, a dismissal)."""
    header = body[:HEADER_CHARS]
    subject = _field(header, r"MATERIAS?")
    subject = _squash(subject) if subject else None
    parsed = Parsed(
        number=_energy_number(header),
        resolved_on=_date(header),
        operator=_energy_operator(header),
        appeal_kind=_energy_kind(summary, subject),
    )
    parsed.subject = subject
    parsed.outcome = _energy_outcome(body)
    parsed.claim_type = claim_type(
        parsed.subject or "", appeal_kind=parsed.appeal_kind, types=ENERGY_CLAIM_TYPES
    )
    if parsed.claim_type is None and (
        parsed.outcome == "sin_efecto"
        or _PROCEDURAL_DISMISSAL.search(_article_paragraphs(_resolutive_tail(body)))
        or re.search(
            r"cautelar|acumul|reclamo\s+gen[eé]rico|queja",
            parsed.subject or "",
            re.IGNORECASE,
        )
    ):
        parsed.claim_type = "procedural"

    checks = (
        ("date", parsed.resolved_on),
        ("operator", parsed.operator),
        ("kind", parsed.appeal_kind),
        ("subject", parsed.subject or parsed.claim_type),
        ("claim_type", parsed.claim_type),
        ("outcome", parsed.outcome),
    )
    parsed.missing = [name for name, value in checks if value is None]
    return parsed


def _energy_number(header: str) -> str | None:
    match = _ENERGY_NUMBER.search(header)
    if not match:
        return None
    return f"{match[1]}-{match[2]}-OS/JARU-{match[3].upper()}"


def _energy_operator(header: str) -> str | None:
    value = _field(
        header,
        r"EMPRESA\s+(?:DISTRIBUIDORA|CONCESIONARIA|LICENCIATARIA|PRESTADORA)|"
        r"EMPRESA|CONCESIONARIA",
    )
    if value:
        # `Enel Distribución Perú S.A.A. (en adelante, Pluz Energía Perú S.A.A.)`
        # prints the name the case was brought against first.
        line = value.splitlines()[0].split("(", 1)[0]
        name = _squash(_plain(line).upper()).rstrip(" .")
        if known := _known_operator(_letters(name), ENERGY_OPERATORS):
            return known
        suffix = _LEGAL_SUFFIX.search(name)
        if suffix:
            name = name[: suffix.end()].rstrip(".") + "."
            close = get_close_matches(name, ENERGY_OPERATORS, n=1, cutoff=0.85)
            return close[0] if close else name
    # No label prints in many JARU formats. The party named after `contra` is
    # the company sued, and the impugnada code is the company's own series.
    if against := re.search(
        r"\bcontra\s+([A-ZÁÉÍÓÚÑ][^\n]{2,70}?(?:S\.A\.A|S\.A\.C|S\.A|S\.R\.L)"
        r"\b\.?)",
        header,
    ):
        name = _squash(_plain(against[1]).upper()).rstrip(" .") + "."
        if known := _known_operator(_letters(name), ENERGY_OPERATORS):
            return known
        close = get_close_matches(name, ENERGY_OPERATORS, n=1, cutoff=0.85)
        return close[0] if close else name
    if match := _IMPUGNADA.search(header):
        return IMPUGNADA_OPERATORS.get(_plain(match[1]).upper())
    return None


def _energy_kind(summary: str, subject: str | None) -> str:
    """Whether the file is an appeal or a queja on the procedure, from the
    `Materia` line first, then the page summary. The antecedents of an appeal
    also mention quejas the company mishandled, so the header prose is not a
    source."""
    if re.match(r"\W*queja\b", _plain(subject or ""), re.IGNORECASE):
        return "queja"
    if re.search(r"\bqueja\b", _plain(summary), re.IGNORECASE):
        return "queja"
    return "apelacion"


def _energy_outcome(body: str) -> str | None:
    """The verdicts the resolutive articles declare. A JARU resolution rules
    claim by claim, so several verdicts make the outcome `mixto`; a `NULA`
    sends the file back without ruling on a claim. A procedural disposition —
    `CARECE DE OBJETO`, `DESESTIMAR`, `ACUMULAR` and the like — is read when
    no verdict word appears."""
    tail = _resolutive_tail(body)
    if re.search(r"FUNDAD[OA]S?\s+EN\s+PARTE", tail, re.IGNORECASE):
        return "fundado_en_parte"
    verdicts = {
        _VERDICTS[_plain(word).lower().rstrip("s")]
        for word in _RULING_WORDS.findall(tail)
    }
    if len(verdicts) > 1:
        return "mixto"
    if verdicts:
        return next(iter(verdicts))
    articles = _article_paragraphs(tail)
    if _PROCEDURAL_DISMISSAL.search(articles):
        return "improcedente"
    if _PROCEDURAL_RULING.search(articles):
        return "sin_efecto"
    return None


def _resolutive_tail(body: str) -> str:
    """The text after the resolutive marker — articles, footnotes and
    signatures as the extractor interleaved them."""
    start = max(
        body.rfind("SE RESUELVE"),
        body.rfind("POR LO TANTO"),
        body.rfind("RESUELVE:"),
    )
    if start < 0 and (match := list(_ARTICLE_ONE.finditer(body))):
        start = match[-1].start()
    return body[start if start >= 0 else -TAIL_CHARS :]


def _article_paragraphs(tail: str) -> str:
    """The paragraphs that open an `Artículo` heading, each through its
    continuation lines up to the next blank line or signature. Footnotes and
    page headers the extractor interleaved never start one, so the procedural
    rules cannot read them."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in tail.splitlines():
        if _ARTICLE_LINE.match(line):
            current = [line]
            paragraphs.append(current)
        elif not line.strip() or _SIGNATURE.match(line):
            current = []
        elif current:
            current.append(line)
    return "\n".join(line for paragraph in paragraphs for line in paragraph)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _number(header: str) -> str | None:
    match = _NUMBER.search(header)
    return f"{match[1]}-{match[2]}-TRASU/OSIPTEL" if match else None


def _date(header: str) -> date | None:
    match = _DATE.search(header)
    if not match:
        return None
    month_name = match[2].lower()
    month = MONTHS.get(month_name)
    if month is None:
        close = get_close_matches(_plain(month_name), MONTHS, n=1, cutoff=0.8)
        month = MONTHS[close[0]] if close else None
    day = _number_in(match[1])
    year = _year_in(match[3])
    if month is None or day is None or year is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _number_in(text: str) -> int | None:
    """A number written in digits or in words from one to fifty-nine."""
    digits = re.fullmatch(r"\s*(\d{1,2})\s*", text)
    if digits:
        return int(digits[1])
    words = [_plain(word).lower() for word in re.findall(r"[^\W\d_]+", text)]
    if len(words) == 1:
        return _UNITS.get(words[0]) or _TENS.get(words[0])
    if len(words) == 3 and words[1] == "y" and words[0] in _TENS and words[2] in _UNITS:
        return _TENS[words[0]] + _UNITS[words[2]]
    return None


def _year_in(text: str) -> int | None:
    # A glued duplicate (`...del 202120 de mayo del 2021`) keeps the first four.
    digits = re.match(r"\s*(\d{4})", text)
    if digits:
        return int(digits[1])
    spelled = re.match(r"\s*dos\s+mil\b\s*([^\n.,;]*)", _plain(text), re.IGNORECASE)
    if not spelled:
        return None
    rest = spelled[1].strip()
    # Scan noise can trail the year, so read the longest number that parses.
    words = rest.split()
    for length in range(min(3, len(words)), 0, -1):
        value = _number_in(" ".join(words[:length]))
        if value is not None:
            return 2000 + value
    return None


def _appeal_kind(header: str) -> str | None:
    match = _EXPEDIENTE.search(header)
    if match:
        return "apelacion" if match[1].upper() == "RA" else "queja"
    upper = _plain(header).upper()
    if "RECURSO DE APELACION" in upper:
        return "apelacion"
    if re.search(r"^\s*QUEJA\s*$", upper, re.MULTILINE):
        return "queja"
    return None


def _field(header: str, label: str) -> str | None:
    """The text after a label, up to the next label. Line breaks are kept."""
    pattern = (
        rf"^{_NOISE}(?:{label})[ \t]*[:;>_\-{_DASHES}]?(.*?)"
        rf"(?=^{_NOISE}(?:{_LABELS})\b|\Z)"
    )
    match = re.search(pattern, header, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if not match:
        return None
    return match[1].lstrip(f":;>_-{_DASHES} \t").strip() or None


def _operator(header: str, summary: str) -> str | None:
    """The operator's name. The page's own `Empresa:` line is typed text, so it
    wins over the scan when the page has one."""
    named = re.search(r"^Empresa:(.*)$", summary, re.IGNORECASE | re.MULTILINE)
    value = named[1] if named else _field(header, r"EMPRESA\s*OPERADORA")
    if not value or not value.strip():
        # A table scanned as columns puts the values after all the labels.
        return _known_operator_in(header)
    name = _squash(_plain(value.splitlines()[0]).upper())
    # Scan noise follows the name on the same line, with or without a space.
    if known := _known_operator(_letters(name)):
        return known
    suffix = _LEGAL_SUFFIX.search(name)
    if not suffix:
        # A name with neither a known operator nor a legal form is a misread
        # box, and a guess would put a wrong operator in the corpus.
        return None
    name = name[: suffix.end()].rstrip(".") + "."
    close = get_close_matches(name, KNOWN_OPERATORS, n=1, cutoff=0.85)
    return close[0] if close else name


def _known_operator_in(header: str) -> str | None:
    for line in header.splitlines():
        if not line.lstrip().startswith(":"):
            continue
        if known := _known_operator(_letters(line)):
            return known
    return None


def _known_operator(
    letters: str, operators: tuple[str, ...] = KNOWN_OPERATORS
) -> str | None:
    """The known operator whose name opens `letters`, allowing for misread letters."""
    for known in operators:
        stem = _letters(_LEGAL_SUFFIX.sub("", known))
        if SequenceMatcher(None, letters[: len(stem)], stem).ratio() >= 0.9:
            return known
    return None


def _letters(text: str) -> str:
    return re.sub(r"[^A-Z]", "", _plain(text).upper())


def _subject(header: str) -> str | None:
    value = _field(
        header,
        r"MATERIA\s+RECLAMADA|CONCEPTOS?\s+(?:RECLAMADOS?|CUESTIONADOS?)|ESCRITO\s+DE\s+QUEJA",
    )
    return _squash(value) if value else None


OUTCOMES = ("infundado", "fundado", "improcedente")
OUTCOME_NAMES = (*OUTCOMES, "fundado_en_parte", "mixto", "sin_efecto")
CLAIM_TYPE_NAMES = (
    *(name for name, _ in CLAIM_TYPES),
    *(name for name, _ in ENERGY_CLAIM_TYPES),
    "procedural",
)


def _outcome(header: str) -> str | None:
    """One outcome, or `mixto` when the Tribunal ruled differently on several claims."""
    value = _field(
        header,
        r"RESOLUCI.N\s+DEL\s+(?:TRIBUNAL|TRASU)|SENTIDO\s+DE\s+LA\s+RESOLUCI.N",
    )
    return _ruling_in(value) if value else None


def _ruling_in(value: str) -> str | None:
    if re.search(r"parcial|en\s+parte", _plain(value), re.IGNORECASE):
        return "fundado_en_parte"
    if re.search(r"sin\s+efecto", _plain(value), re.IGNORECASE):
        return "sin_efecto"
    # Each ruling is written in capitals. The prose after it is not.
    rulings = {
        ruling
        for word in re.findall(r"\b[A-ZÁÉÍÓÚÑ0-9]{6,}\b", value)
        if (ruling := _ruling(word))
    }
    if len(rulings) > 1:
        return "mixto"
    return next(iter(rulings), None)


def _sumilla_ruling(summary: str) -> str | None:
    """The ruling the page's own summary states, as in `Declaran fundada ...`,
    typed in lower case as often as in capitals."""
    declared = re.search(r"Declar\w*\s+([^\n]*\n?[^\n]*)", summary, re.IGNORECASE)
    if not declared:
        return None
    text = _plain(declared[1][:80]).lower()
    if re.search(r"parcial|en\s+parte", text):
        return "fundado_en_parte"
    if re.search(r"sin\s+efecto", text):
        return "sin_efecto"
    for word in re.findall(r"[a-z]{6,}", text):
        if ruling := _ruling(word):
            return ruling
    return None


def _sumilla_kind(summary: str) -> str | None:
    """Whether the summary says the resolution decides an appeal or a complaint."""
    declared = re.search(r"Declar\w*\s+([^\n]*\n?[^\n]*)", summary, re.IGNORECASE)
    if not declared:
        return None
    text = _plain(declared[1][:120]).lower()
    appeal = "apelacion" in text
    complaint = re.search(r"\bqueja\b", text) is not None
    if appeal != complaint:
        return "apelacion" if appeal else "queja"
    return None


def _sumilla_topic(summary: str) -> str:
    """What the summary says the claim was about: its first sentence-sized stretch."""
    return summary.split("Sumilla:", 1)[-1][:400]


def _ruling(word: str) -> str | None:
    """The outcome a capitalized word names, allowing for the feminine and scan errors."""
    text = _plain(word).lower()
    if text.endswith("a"):
        text = text[:-1] + "o"
    close = get_close_matches(text, OUTCOMES, n=1, cutoff=0.8)
    return close[0] if close else None
