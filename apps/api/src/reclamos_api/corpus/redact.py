"""Replace the data that identifies a person with a fixed label.

A resolution names the complainant, the line in dispute and sometimes a home
address, an email or a DNI. It also names the vocales and secretaries who sign
it, the officials who act for OSIPTEL and the operator's staff and addresses:
those stay, as do resolution numbers, expedientes, norms, dates and amounts.

The rules layer covers the typed cases: honorifics ("la señora ..."),
"identificado con", the RECLAMANTE header field, document and phone labels and
address verbs. A local Spanish NER model (es_core_news_sm, added through uv)
covers the person names the rules miss. A PER entity is kept when it sits
inside a signature or title context; anything else the model calls a person is
redacted, because a missed complainant is worse than an over-redacted word.

`REDACTOR_VERSION` marks what wrote a `redacted_body`: a change to the
patterns or the model bumps it, and the next crawl or reindex re-redacts.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

REDACTOR_VERSION = "14"
DEFAULT_NER_MODEL = "es_core_news_sm"

LABELS = {
    "nombre": "[NOMBRE]",
    "dni": "[DNI]",
    "telefono": "[TELÉFONO]",
    "correo": "[CORREO]",
    "direccion": "[DIRECCIÓN]",
    "codigo": "[CÓDIGO]",
}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

_DOCUMENT_LABELS = (
    r"(?:D\.?\s?N\.?\s?I\.?|C\.?\s?E\.?|d\w{0,4}umento\s+(?:nacional\s+)?(?:de\s+)?identidad|"
    r"identidad|"
    r"pasaporte|libreta\s+(?:electoral|militar)|carnet\s+de\s+extranjer[ií]a)"
)
_DOCUMENT = re.compile(
    rf"{_DOCUMENT_LABELS}\b[\s,°ºNnro.:*#?«»\"'“”\-]*?\b(\d[\d .-]{{5,14}}\d)\b",
    re.IGNORECASE,
)
_IDENTIFIED = re.compile(
    r"identificad[oa]s?\s+(?:debidamente\s+)?con\s+"
    rf"(?:{_DOCUMENT_LABELS}\b[\s,°ºNnro.:*#?«»\"'“”\-]*?)?(\d[\d .-]{{5,14}}\d)\b",
    re.IGNORECASE,
)

_PHONE_LABELS = (
    r"l[ií]neas?(?:\s+telef[oó]nicas?)?(?:\s+fijas?|m[oó]viles?|celular(?:es)?|"
    r"\s+de\s+contacto)?|tel[eé]fonos?(?:\s+fijos?|celular(?:es)?)?|"
    r"n[uú]meros?\s+de\s+(?:servicio|l[ií]nea|tel[eé]fono|contacto)|"
    r"servicio\s+(?:fijo|m[oó]vil|telef[oó]nico)|anexo"
)
_PHONE = re.compile(
    rf"(?:{_PHONE_LABELS})\b[\s,°ºNnro.:*#?«»\"'“”\-]*?\b(\d[\d .-]{{4,15}}\d)\b",
    re.IGNORECASE,
)
# A standalone nine-digit mobile number, with or without separators inside.
# Expediente and resolution numbers carry dashes or letters, so a bare
# nine-digit run is always a line.
_MOBILE = re.compile(
    r"(?<![\d./-])(9\d{8}|0?\d{2,3}[ -]9\d{8}|\(\d{2,3}\)\s*9\d{8}|"
    r"9\d{2}[ -]\d{3}[ -]\d{3}|9\d{2}-\d{6})(?![\d/-])"
)
# The operator's published service channels keep their numbers: WhatsApp,
# call-center and office lines are public record, not a complainant's line.
# A number is kept only when a channel label sits directly before it.
_PUBLIC_CHANNEL = re.compile(
    r"(?:whatsapp|call\s?center|mesa\s+de\s+partes|"
    r"atenci[oó]n\s+al\s+cliente|central\s+telef[oó]nica|servicio\s+al\s+cliente|"
    r"canal\s+de\s+atenci[oó]n)\W{0,8}$",
    re.IGNORECASE,
)

_CODE_LABELS = (
    r"c[oó]digos?\s+(?:de\s+)?(?:reclamo|cliente|contrato|abonado|servicio|"
    r"cuenta|pedido|usuario|suscriptor)|c[oó]digo\s+[uú]nico\s+de\s+contrato|"
    r"n[uú]meros?\s+de\s+(?:reclamo|contrato|cuenta|pedido|expediente\s+del\s+reclamo)|"
    r"cuenta\s+de\s+(?:ahorros|facturaci[oó]n)|contrato\s+(?:n[°º.]?\s*)|"
    r"n[uú]meros?\s+CID|"
    r"(?:reclamos?|solicitud(?:es)?|pedidos?)\s+(?:con\s+)?n[°ºro.*?\"'“”«»-]*"
)
_CODE = re.compile(
    rf"(?:{_CODE_LABELS})\b[\s,°ºNnro.:*#?«»\"'“”\-]*?\b([A-Z0-9][A-Z0-9 ./-]{{4,24}}[A-Z0-9])\b",
    re.IGNORECASE,
)

# A private address is a street word, then the street name and its number. The
# abbreviation dot sits outside the word match so "Jr." and "Av." fire; the
# span ends at a comma (before the district), a sentence end or a line break.
_ADDRESS = re.compile(
    r"(?i:avenida|av|jir[oó]n|jr|calle|ca|pasaje|psje|mz|manzana|lote|lt|"
    r"dpto|departamento|interior|int|urbanizaci[oó]n|urb|"
    r"asentamiento\s+humano|aa\.?\s?hh\.?|sector|cuadra|prolongaci[oó]n|"
    r"carretera|km)\.?\s+"
    r"(?=[A-Z0-9ÁÉÍÓÚÑ][^\n,.;()]*\d)[A-Z0-9ÁÉÍÓÚÑ][^\n,.;()]*"
)
_ADDRESS_LEAD = re.compile(
    r"(?:domicilio(?:\s+(?:real|procesal|legal))?|direcci[oó]n|residencia)\s+"
    r"(?:(?:de\s+la|del)\s+(?:reclamant|recurrent|usuari|denunciant|suscrit|"
    r"solicitant|apoderad|titular|client|abonad|señor|señora|empresarial|"
    r"interesad|administrad)[a-z]*\s*"
    r"(?:,?\s*(?:es|se\s*(?:ñala|encuentra|ubica)?|consignad?[oa]?|"
    r"declarad?[oa]?|ubicad?[oa]|sitad?[oa]|domiciliad?[oa])\s*(?:es|en|que)?\s*|"
    r"\b(?:en|es)\s+)"
    r"|(?:el|la|en)\s+)",
    re.IGNORECASE,
)
# The institution's own seat and any company's legal address are public record.
_PUBLIC_ADDRESS = re.compile(
    r"(?:de\s+la\s+)?prosa\b|san\s+borja\b|osiptel\b|miraflores.{0,40}v[ií]a\s+l[aá]ctea",
    re.IGNORECASE,
)

_HONORIFIC = re.compile(
    r"(?:la\s+señora|el\s+señor|[Ss]eñor(?:a|ita)?|[Dd]oña|[Dd]on|[Ss]rta?\.?)\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+"
    r"(?:\s+(?:(?:de|del|la|los|y)\s+){0,2}[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,4})",
)
_PUBLIC_ROLES = re.compile(
    r"(?:vocales?|vocalista|secretari[oa]|president[ae]?|secretar[ií]a\s+t[eé]cnica|"
    r"colegiad[oa]s?|jefe|gerente\s+general|director[ae]?\s+general|fiscal|"
    r"especialista\s+legal|asesor(?:a)?\s+legal|procurador[ae]?\s+p[úu]blico|"
    r"miembros?|integrantes)\b",
    re.IGNORECASE,
)
_STAFF_ROLE = re.compile(
    r"(?:asesor(?:a)?\s+de\s+la\s+empresa|personal\s+de\s+la\s+empresa|"
    r"trabajador(?:a)?\s+de\s+la\s+empresa|ejecutiv[oa]\s+de\s+la\s+empresa|"
    r"representante|apoderad[oa]|gestor|operador(?:a)?|t[eé]cnico|instalador|"
    r"vendedor(?:a)?|encargad[oa]|responsable)\b",
    re.IGNORECASE,
)
_NAME_IN_FIELD = re.compile(
    r"^(?:RECLAMANTE|DENUNCIANTE|RECURRENTE|USUARIO|TITULAR|APELANTE|"
    r"SOLICITANTE|COMPARECIENTE|INTERESADO|SUSCRIPTOR|ABONADO)\s*[.:;]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_SIGNATURE_ZONE = re.compile(
    r"(?:con\s+la\s+intervenci[oó]n\s+de|presidente\s+del\s+tribunal|"
    r"vocal(?:es)?\b.{0,80}\b(?:vocal(?:es)?|firma)|secretar[ií]a\s+t[eé]cnica|"
    r"suscrib\w*\s+la\s+presente|firma(?:n|do|mos)?\s+la\s+presente|"
    r"reg[ií]strese\s+y\s+notif[ií]quese|lo\s+que\s+certifico)",
    re.IGNORECASE,
)
# Signer blocks that print the name before the marker: "Firmado digitalmente
# por MENDOZA CHOZA X FAU 20216072155/soft Vocal de la Sala Unipersonal".
_SIGNATURE_AFTER = re.compile(
    r"(?:digitalmente|ígitalmente|gitalmente)\s+p[oó]r|FAU\s+\d+|"
    r"vocal\s+de\s+la\s+sala|sala\s+unipersonal",
    re.IGNORECASE,
)
_COMPANY_TAIL = re.compile(
    r"\b(?:S\.?\s?A\.?(?:\s?A\.?|\s?C\.?)?|S\.?\s?R\.?\s?L\.?|E\.?\s?I\.?\s?R\.?\s?L\.?|"
    r"PER[ÚU]|TELECOM|MOVISTAR|CLARO|ENTEL|BITEL|OSIPTEL|AMERICATEL|TELMEX|"
    r"VIETTEL|INTEGRATEL|TELEF[OÓ]NICA|WIN|WOW|GILAT|HUGHESNET|STARLINK)\b\.?",
    re.IGNORECASE,
)
_NAME_SHAPE = re.compile(
    r"^[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:\s+(?:de|del|la|los|y|da|di|van|von)\s+|\s+)"
    r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+)*$"
)
_NAME_TOKEN = re.compile(r"^[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+$")
_FIELD_TOKEN = re.compile(r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñü]+")
_FIELD_VALUE = re.compile(
    r"^\s*[A-ZÁÉÍÓÚÑa-záéíóúñü]+(?:[\s,'.-]+[A-ZÁÉÍÓÚÑa-záéíóúñü]+)*"
)
_NAME_CONNECTORS = frozenset(
    {"de", "del", "la", "los", "las", "y", "da", "di", "van", "von", "e"}
)
# Words a header value can carry that are never a private person: connectors,
# generic terms, and institution or product names. Field tokens matching any
# of these never feed the name-occurrence search.
_FIELD_STOP = _NAME_CONNECTORS | frozenset(
    {
        "a",
        "al",
        "con",
        "el",
        "en",
        "es",
        "lo",
        "o",
        "para",
        "por",
        "se",
        "su",
        "sus",
        "un",
        "una",
        "u",
        "administrativo",
        "administrativos",
        "ano",
        "area",
        "apelacion",
        "asociacion",
        "bcp",
        "bitel",
        "calle",
        "claro",
        "codigo",
        "comercial",
        "comercializadora",
        "compania",
        "departamento",
        "direccion",
        "distrito",
        "domicilio",
        "empresa",
        "entel",
        "expediente",
        "fecha",
        "general",
        "gerencia",
        "gobierno",
        "independencia",
        "inversion",
        "inversiones",
        "junta",
        "junin",
        "lima",
        "linea",
        "los",
        "ministerio",
        "movistar",
        "municipalidad",
        "nacional",
        "numero",
        "oficina",
        "operadora",
        "osi",
        "osiptel",
        "peru",
        "plan",
        "poder",
        "premium",
        "privada",
        "procedimiento",
        "prosa",
        "provincia",
        "publica",
        "publico",
        "publicos",
        "queja",
        "reclamante",
        "reclamo",
        "recurso",
        "regional",
        "resolucion",
        "saa",
        "sac",
        "sede",
        "servicio",
        "servicios",
        "sociedad",
        "solucion",
        "speedy",
        "srl",
        "telecomunicaciones",
        "telefonia",
        "telefonica",
        "telefono",
        "tgs",
        "titular",
        "tribunal",
        "unidad",
        "usuario",
        "usuarios",
        "vocal",
        "vocales",
        "aaa",
        "asimismo",
        "cable",
        "consejo",
        "cumplir",
        "directivo",
        "elije",
        "gprs",
        "heee",
        "infointernet",
        "instancia",
        "intemat",
        "internet",
        "ldi",
        "ley",
        "premiun",
        "reclamos",
        "recursos",
        "sin",
        "tal",
    }
)


def _fold(word: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", word.lower())
        if unicodedata.category(c) != "Mn"
    )


# Words a Peruvian legal text capitalizes mid-sentence but that never belong
# to a person. The NER model calls several of them a person.
_NON_NAME_WORDS = frozenset(
    [
        "abonado",
        "acciones",
        "acta",
        "adicional",
        "administrativo",
        "alegaciones",
        "apelacion",
        "apelante",
        "area",
        "articulo",
        "asunto",
        "atencion",
        "autoridad",
        "averias",
        "beneficio",
        "carne",
        "carnet",
        "carta",
        "centro",
        "certificacion",
        "certificado",
        "circular",
        "cliente",
        "codigo",
        "compareciente",
        "competencia",
        "complementarias",
        "comunicaciones",
        "concesionario",
        "condiciones",
        "consejo",
        "constancia",
        "consultas",
        "consumidor",
        "contrato",
        "correo",
        "cuenta",
        "cuotas",
        "dactilar",
        "defensa",
        "defensoria",
        "denuncia",
        "denunciante",
        "departamento",
        "digital",
        "direccion",
        "directiva",
        "division",
        "distrito",
        "documento",
        "documentacion",
        "domicilio",
        "electronico",
        "emision",
        "empresa",
        "equipo",
        "estado",
        "extranjeria",
        "factura",
        "facturacion",
        "fau",
        "fecha",
        "firma",
        "fiscalizacion",
        "fijo",
        "financiamiento",
        "fiscal",
        "gestion",
        "gobierno",
        "historico",
        "horario",
        "huella",
        "identidad",
        "ilimitado",
        "imei",
        "importe",
        "impugnada",
        "incidencias",
        "indecopi",
        "informatica",
        "informe",
        "instalacion",
        "instruccion",
        "intelectual",
        "inversion",
        "juzgado",
        "legal",
        "ley",
        "libreta",
        "lima",
        "linea",
        "lineamientos",
        "marca",
        "materia",
        "medios",
        "mecanismo",
        "medio",
        "ministerio",
        "modelo",
        "monto",
        "movil",
        "nacional",
        "norma",
        "normas",
        "notificacion",
        "nro",
        "numero",
        "oferta",
        "oficio",
        "oficina",
        "operadora",
        "organismo",
        "organizacion",
        "pago",
        "pasaporte",
        "pedido",
        "pedidos",
        "personales",
        "peru",
        "peticiones",
        "plan",
        "plaza",
        "politica",
        "portabilidad",
        "postpago",
        "precedente",
        "precio",
        "prepago",
        "presidencia",
        "previo",
        "privada",
        "privacidad",
        "probatorios",
        "procedimiento",
        "promocion",
        "propiedad",
        "proteccion",
        "provincia",
        "publico",
        "publicos",
        "reclamante",
        "reclamo",
        "reclamos",
        "recurrente",
        "registro",
        "reglamento",
        "reniec",
        "relacion",
        "reportes",
        "resolucion",
        "resolutivo",
        "responsable",
        "sala",
        "seguros",
        "sello",
        "senal",
        "servicio",
        "servicios",
        "sistema",
        "solicito",
        "solicitud",
        "sos",
        "solucion",
        "supervisor",
        "suspension",
        "suspensiones",
        "telefonico",
        "tarifas",
        "telefonia",
        "telecomunicaciones",
        "telefonica",
        "terminal",
        "texto",
        "tiempo",
        "titular",
        "tramite",
        "tribunal",
        "unidad",
        "unicacion",
        "unico",
        "unipersonal",
        "usuario",
        "usuarios",
        "validez",
        "vencimiento",
        "verificacion",
        "vigencia",
        "vocal",
        "vocales",
    ]
)
# A NER person is only plausible inside a context a legal text gives a person:
# an honorific or role word in front, or a document clause behind.
_PERSON_BEFORE = re.compile(
    r"(?:señor(?:a|es|ita)?|señorita|doña|don|dra?\.?|ing\.?|lic\.?|arq\.?|"
    r"srta?\.?|identificad[oa]s?|denominad[oa]s?|llamad[oa]s?|apoderad[oa]s?|"
    r"representante|suscrit[oa]s?|titular(?:es)?|asesor[ae]?s?|gestor[ae]?|"
    r"operador[ae]?|trabajador[ae]?|emplead[oa]s?|vendedor[ae]?|instalador|"
    r"compareciente|contratante|de\s+nombre|por\s+nombre|nombre\s+(?:de|del))\W{0,25}$",
    re.IGNORECASE,
)
_PERSON_AFTER = re.compile(
    r"^\W{0,10}(?:identificad[oa]s?\s+)?(?:con|de)\s+"
    r"(?:D\.?\s?N\.?\s?I\.?|C\.?\s?E\.?|documento|DNI|carnet|pasaporte|"
    r"domicilio|direcci[oó]n|la\s+firma)\b|"
    r"^\W{0,10}(?:el|la)\s+"
    r"(?:reclamante|denunciante|recurrente|titular|solicitante|usuario|"
    r"apelante|compareciente|interesado)\b",
    re.IGNORECASE,
)
_ADDRESS_BEFORE = re.compile(
    r"(?:avenida|av\.?|jir[oó]n|jr\.?|calle|ca\.?|pasaje|psje\.?|"
    r"urbanizaci[oó]n|urb\.?|carretera|prolongaci[oó]n)\s*$",
    re.IGNORECASE,
)
_INITIALISM = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{3,}\b")
# A staff name follows an explicit cue: a role word, a self-introduction, a
# speaker label, an email header or a greeting. Without the cue the same name
# shape belongs to institutions ("la Gerencia General de Telefónica").
_STAFF_NAME = re.compile(
    r"(?:\b(?i:(asesor[ae]?s?|ejecutiv[oa]s?|agente|"
    r"(?<!(?i:empresa)\s)(?<!(?i:empresas)\s)operador[ae]?s?|"
    r"funcionari[oa]s?|representantes?|trabajador[ae]?s?)\b\s*[:.,;\-]?"
    r"|mi\s+nombre\s+es|le\s+habla|le\s+saluda|estimad[oa]s?|"
    r"enviado\s+por|sra?\.?\b\s*[:.,;\-]?)"
    r"|^Para\s*:|^De\s*:)"
    r"(?:\s+(?:(?i:de|del|la|los|las|el|en|a|al|y|e|u|con|por|para|que|se|"
    r"su|sus|atención|empresarial|empresariales|empresa|operadora|"
    r"comercial|corporativa|área|departamento|oficina|unidad|dirección|"
    r"gerencia|mesa|partes|call|center|nacional|internacional|senior|"
    r"cliente|clientes|servicios)\b|(?!\S*[A-ZÁÉÍÓÚÑ])\S*[^\w\s.!?]\S*|"
    r"[a-záéíóúñü0-9]*[0-9,:;!?][a-záéíóúñü0-9]*[,:;!?]*)){0,8}"
    r"(?:\s+[Ss]eñor(?:a|ita)?\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+\s*,)?"
    r"\s*([A-ZÁÉÍÓÚÑ][a-záéíóúñü]+"
    r"(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+){0,3}"
    r"(?:\s+[A-ZÁÉÍÓÚÑ]{1,3}\.?(?![a-záéíóúñü])){0,3})",
    re.MULTILINE,
)
_ALLCAPS_NAME = re.compile(
    r"\b(?:[Ll]a\s+[Ss]eñora|[Ee]l\s+[Ss]eñor|[Ss]eñora|[Ss]eñor|[Dd]oña|[Dd]on)\s+"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñü]+(?:\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñü]+){1,4})"
)


class Nlp(Protocol):
    def __call__(self, text: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    label: str


class Redactor:
    """Replaces identifying data with labels. The NER model is optional: the
    rules alone already redact honorifics, fields, documents and lines."""

    def __init__(self, nlp: Nlp | None, *, ner_limit: int = 100_000) -> None:
        self._nlp = nlp
        self.ner_limit = ner_limit
        self.version = REDACTOR_VERSION

    @classmethod
    def without_ner(cls) -> "Redactor":
        return cls(None)

    def load(self) -> None:
        if self._nlp is None:
            raise RuntimeError("no NER model: pass one or use without_ner")
        self._nlp("test")

    def redact(self, text: str) -> str:
        if not text:
            return text
        spans = [
            *_regex_spans(text),
            *_person_spans(text),
        ]
        if self._nlp is not None:
            spans += _ner_spans(self._nlp, text[: self.ner_limit])
        return _apply(text, _keep_suppressed(spans, _public_zones(text)))

    def counts(self, text: str) -> dict[str, int]:
        redacted = self.redact(text)
        return {
            name: redacted.count(label)
            for name, label in LABELS.items()
            if redacted.count(label)
        }


def redactor_from_settings(settings: Any) -> Redactor:
    model = getattr(settings, "redaction_model", DEFAULT_NER_MODEL) or DEFAULT_NER_MODEL
    import spacy

    return Redactor(spacy.load(model))


def _regex_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for match in _EMAIL.finditer(text):
        spans.append(_Span(match.start(), match.end(), "correo"))
    for pattern, label in (
        (_DOCUMENT, "dni"),
        (_IDENTIFIED, "dni"),
        (_PHONE, "telefono"),
        (_MOBILE, "telefono"),
        (_CODE, "codigo"),
    ):
        spans += _group_spans(pattern, text, label)
    for match in _ADDRESS_LEAD.finditer(text):
        tail = match.end()
        follow = _ADDRESS.match(text, tail)
        if follow is not None and not _PUBLIC_ADDRESS.search(follow.group()):
            spans.append(_Span(follow.start(), follow.end(), "direccion"))
    return spans


def _group_spans(pattern: re.Pattern[str], text: str, label: str) -> list[_Span]:
    out: list[_Span] = []
    for match in pattern.finditer(text):
        start, end = match.span(1)
        value = match.group(1)
        digits = re.sub(r"\D", "", value)
        if label in ("dni", "telefono") and (
            not 6 <= len(digits) <= 11
            and not (("-" in value or " " in value) and len(digits) <= 13)
        ):
            continue
        if label == "telefono" and _PUBLIC_CHANNEL.search(text[:start]):
            continue
        out.append(_Span(start, end, label))
    return out


def _person_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for pattern in (_HONORIFIC, _ALLCAPS_NAME):
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            if _public_name(text, match.start(1), name):
                continue
            spans.append(_Span(match.start(1), match.end(1), "nombre"))
    for match in _STAFF_NAME.finditer(text):
        tokens = list(re.finditer(r"\S+", match.group(2)))
        while tokens and _fold(tokens[0].group(0)) in _NAME_CONNECTORS:
            tokens.pop(0)
        if not tokens:
            continue
        name = match.group(2)[tokens[0].start() : tokens[-1].end()]
        if any(
            not (
                _NAME_TOKEN.match(token.group(0))
                or re.fullmatch(r"[A-ZÁÉÍÓÚÑ]{1,3}\.?", token.group(0))
            )
            or (
                _NAME_TOKEN.match(token.group(0))
                and _fold(token.group(0)) in _FIELD_STOP | _NON_NAME_WORDS
            )
            for token in tokens
        ):
            continue
        if match.group(1) and len(tokens) < 2:
            continue
        if _public_name(text, match.start(2), name):
            continue
        spans.append(
            _Span(
                match.start(2) + tokens[0].start(),
                match.start(2) + tokens[-1].end(),
                "nombre",
            )
        )
    for match in _NAME_IN_FIELD.finditer(text):
        value = _FIELD_VALUE.match(match.group(1))
        if value is None:
            continue
        words = re.findall(r"[\wÁÉÍÓÚÜÑáéíóúüñ]+", value.group(0))
        # A field whose value contains prose words is not a name source:
        # "abonado con el RENIEC" would otherwise redact every RENIEC and
        # "RECLAMANTE : SERVICIO TELEFÓNICO ; SOS" would leak "TELEFÓNICO".
        if not words or any(
            _fold(word) not in _NAME_CONNECTORS
            and len(word) >= 3
            and not _FIELD_TOKEN.fullmatch(word)
            for word in words
        ):
            continue
        tokens = [
            token
            for token in _FIELD_TOKEN.findall(value.group(0))
            if len(token) >= 3 and _fold(token) not in _FIELD_STOP | _NON_NAME_WORDS
        ]
        if not tokens:
            continue
        if len(tokens) == 1:
            names = re.compile(r"\b" + re.escape(tokens[0]) + r"\b", re.IGNORECASE)
        else:
            names = re.compile(
                r"\b(?:"
                + "|".join(map(re.escape, tokens))
                + r")\b(?:\s*,?\s+(?:"
                + "|".join(map(re.escape, tokens))
                + r")\b|\s+[A-ZÁÉÍÓÚÑ]\.)+",
                re.IGNORECASE,
            )
        for occurrence in names.finditer(text):
            spans.append(_Span(occurrence.start(), occurrence.end(), "nombre"))
    return spans


def _ner_spans(nlp: Nlp, text: str) -> list[_Span]:
    doc = nlp(text)
    spans: list[_Span] = []
    for entity in doc.ents:
        if entity.label_ != "PER":
            continue
        name = entity.text.strip()
        if len(name) < 3 or _COMPANY_TAIL.search(name):
            continue
        if not _plausible_name(name):
            continue
        if _ADDRESS_BEFORE.search(
            text[max(0, entity.start_char - 30) : entity.start_char]
        ):
            continue
        before = text[max(0, entity.start_char - 90) : entity.start_char]
        after = text[entity.end_char : entity.end_char + 60]
        if not (_PERSON_BEFORE.search(before) or _PERSON_AFTER.search(after)):
            continue
        if _public_name(text, entity.start_char, name):
            continue
        spans.append(_Span(entity.start_char, entity.end_char, "nombre"))
    return spans


def _plausible_name(name: str) -> bool:
    """Two to five proper-case tokens without a legal or institutional word.
    A Peruvian name can carry connectors like "de la"; a company tail or an
    all-caps token marks an institution."""
    tokens = name.split()
    if not 2 <= len(tokens) <= 5:
        return False
    content = 0
    for token in tokens:
        lowered = token.lower().strip(".,;:()")
        if lowered in _NAME_CONNECTORS:
            continue
        if lowered in _NON_NAME_WORDS:
            return False
        if not _NAME_TOKEN.match(token):
            return False
        content += 1
    return content >= 2


def _public_zones(text: str) -> list[_Span]:
    """Spans where a person is public record: signatures, the vocales'
    intervention and officials named in their role."""
    zones: list[_Span] = []
    for match in _SIGNATURE_ZONE.finditer(text):
        zones.append(_Span(match.start(), min(len(text), match.end() + 400), "keep"))
    for match in _SIGNATURE_AFTER.finditer(text):
        zones.append(
            _Span(
                max(0, match.start() - 120), min(len(text), match.end() + 200), "keep"
            )
        )
    return zones


def _public_name(text: str, start: int, name: str) -> bool:
    """A name is public record inside a signature zone, next to a public role
    word, or when it is a company tail."""
    if _COMPANY_TAIL.search(name):
        return True
    window = text[max(0, start - 70) : start + len(name) + 70]
    return bool(_PUBLIC_ROLES.search(window) and not _STAFF_ROLE.search(window))


def _keep_suppressed(spans: list[_Span], zones: list[_Span]) -> list[_Span]:
    return [
        span
        for span in spans
        if not any(zone.start <= span.start < zone.end for zone in zones)
    ]


def _apply(text: str, spans: list[_Span]) -> str:
    ordered = sorted(spans, key=lambda s: (s.start, -s.end))
    merged: list[_Span] = []
    for span in ordered:
        if merged and span.start < merged[-1].end:
            if span.end > merged[-1].end:
                merged[-1] = _Span(merged[-1].start, span.end, merged[-1].label)
            continue
        merged.append(span)
    pieces: list[str] = []
    cursor = 0
    for span in merged:
        pieces.append(text[cursor : span.start])
        pieces.append(LABELS[span.label])
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)
