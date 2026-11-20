"""Write one resolution's case card with a language model, and check it.

A card holds five fields a reader needs to compare their case with this one,
and the model's own reading of the outcome, the operator and the date. A field
is a few points, each one sentence with the quote from the body that says it,
so a reader can check every sentence against its own quote. A point whose quote
is not in the body is dropped, and a field with no point left is dropped with
it.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from reclamos_api.corpus.sources import Sector
from reclamos_api.llm.client import LanguageModel, Prompt
from reclamos_api.llm.quotes import is_quoted
from reclamos_api.llm.spend import Budget, Ledger

# The longest body in the corpus is 47,053 characters (2026-11-14).
MAX_CARD_PROMPT_CHARS = 60_000
MAX_CARD_TOKENS = 3_000
CARD_TIMEOUT_S = 180.0
# Points kept per field. More would make the card harder to read, not truer.
MAX_POINTS = 3

FIELDS = ("claim", "operator_position", "reasoning", "evidence", "orders")
READINGS = ("outcome", "operator", "resolved_on")
OUTCOMES = (
    "fundado",
    "infundado",
    "fundado_en_parte",
    "improcedente",
    "mixto",
    "sin_efecto",
)

SYSTEM = """\
Lees resoluciones del TRASU, el tribunal de OSIPTEL que resuelve las \
apelaciones y quejas de usuarios de telecomunicaciones del Perú. De cada \
resolución escribes una ficha para que un usuario compare su caso con este.

Campos de la ficha:
- claim: qué reclamó el usuario y qué pidió.
- operator_position: qué dijo o decidió la empresa operadora antes de la \
apelación o la queja.
- reasoning: por qué el tribunal decidió lo que decidió.
- evidence: la prueba que decidió el caso, o la prueba que faltó.
- orders: qué ordenó el tribunal en la parte resolutiva, por ejemplo que la \
empresa anule un cobro, devuelva un monto, reponga el servicio o informe de \
lo que hizo. Si no ordenó nada a la empresa, qué declaró.

Cada campo es una lista de uno a tres puntos, del más importante al menos \
importante. Un punto tiene:
- "quote": una cita del texto. Escríbela primero.
- "text": una oración corta de español sencillo que dice lo que dice esa cita.

Reglas:
- Usa solo el texto de la resolución. No uses otro conocimiento.
- Cada oración dice solo lo que dice su propia cita. Lo que la cita no dice no \
va en la oración, aunque otra parte del texto lo diga: ni motivos, ni fechas, \
ni montos, ni nombres, ni detalles, ni consejos.
- Un punto dice un solo hecho. Dos hechos con dos citas son dos puntos.
- Atribuye cada cosa a quien la dijo en la cita: el usuario, la empresa o el \
tribunal.
- Cada cita copia, carácter por carácter, de una a tres oraciones completas \
del texto. Una cita que termina en dos puntos o a mitad de una idea no dice \
nada: copia también lo que sigue. No corrijas errores de escritura ni de OCR, \
y no cambies palabras.
- Si el texto no dice algo que un campo pide, deja su lista vacía.

Además lee del texto:
- outcome: lo que el tribunal declaró sobre la apelación o la queja en la \
parte resolutiva. Usa "mixto" si declaró cosas distintas sobre partes del \
caso.
- operator: el nombre de la empresa operadora como aparece en el texto.
- resolved_on: la fecha de la resolución, en formato AAAA-MM-DD.
Cada lectura lleva la cita del texto que la muestra. Si el texto no la \
muestra, deja "value" y "quote" vacíos.
"""

# The energy prompt keeps the same fields, the same quote rules and the same
# readings; it names the JARU instead of the TRASU, and what the sector calls
# the company instead of "empresa operadora".
ENERGY_SYSTEM = """\
Lees resoluciones de la JARU, la Junta de Apelaciones de Reclamos de Usuarios \
de Osinergmin, que resuelve las apelaciones y quejas de usuarios de \
electricidad y gas natural del Perú. De cada resolución escribes una ficha \
para que un usuario compare su caso con este.

Campos de la ficha:
- claim: qué reclamó el usuario y qué pidió.
- operator_position: qué dijo o decidió la empresa concesionaria o \
distribuidora antes de la apelación o la queja.
- reasoning: por qué el tribunal decidió lo que decidió.
- evidence: la prueba que decidió el caso, o la prueba que faltó.
- orders: qué ordenó el tribunal en la parte resolutiva, por ejemplo que la \
empresa anule un cobro, emita un nuevo pronunciamiento, devuelva un monto, \
reponga el suministro o informe de lo que hizo. Si no ordenó nada a la \
empresa, qué declaró.

Cada campo es una lista de uno a tres puntos, del más importante al menos \
importante. Un punto tiene:
- "quote": una cita del texto. Escríbela primero.
- "text": una oración corta de español sencillo que dice lo que dice esa cita.

Reglas:
- Usa solo el texto de la resolución. No uses otro conocimiento.
- Cada oración dice solo lo que dice su propia cita. Lo que la cita no dice no \
va en la oración, aunque otra parte del texto lo diga: ni motivos, ni fechas, \
ni montos, ni nombres, ni detalles, ni consejos.
- Un punto dice un solo hecho. Dos hechos con dos citas son dos puntos.
- Atribuye cada cosa a quien la dijo en la cita: el usuario, la empresa o el \
tribunal.
- Cada cita copia, carácter por carácter, de una a tres oraciones completas \
del texto. Una cita que termina en dos puntos o a mitad de una idea no dice \
nada: copia también lo que sigue. No corrijas errores de escritura ni de OCR, \
y no cambies palabras.
- Si el texto no dice algo que un campo pide, deja su lista vacía.

Además lee del texto:
- outcome: lo que el tribunal declaró sobre la apelación o la queja en la \
parte resolutiva. Usa "mixto" si declaró cosas distintas sobre partes del \
caso.
- operator: el nombre de la empresa concesionaria o distribuidora como \
aparece en el texto.
- resolved_on: la fecha de la resolución, en formato AAAA-MM-DD.
Cada lectura lleva la cita del texto que la muestra. Si el texto no la \
muestra, deja "value" y "quote" vacíos.
"""

SYSTEMS: dict[Sector, str] = {"telecom": SYSTEM, "energy": ENERGY_SYSTEM}


def _field_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            # The quote comes first so the model writes the sentence from it.
            "properties": {"quote": {"type": "string"}, "text": {"type": "string"}},
            "required": ["quote", "text"],
            "additionalProperties": False,
        },
    }


def _reading_schema(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": value, "quote": {"type": "string"}},
        "required": ["value", "quote"],
        "additionalProperties": False,
    }


SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **{name: _field_schema() for name in FIELDS},
        "outcome": _reading_schema({"type": "string", "enum": [*OUTCOMES, ""]}),
        "operator": _reading_schema({"type": "string"}),
        "resolved_on": _reading_schema({"type": "string"}),
    },
    "required": [*FIELDS, *READINGS],
    "additionalProperties": False,
}

# A card written with another prompt or schema is out of date. Each sector
# versions its own prompt, so a change to one makes only its cards stale.
PROMPT_VERSIONS = {
    sector: hashlib.sha256(
        (system + json.dumps(SCHEMA, sort_keys=True)).encode()
    ).hexdigest()[:12]
    for sector, system in SYSTEMS.items()
}


@dataclass(frozen=True, slots=True)
class Point:
    text: str
    quote: str


# A field's points, most important first.
type Points = tuple[Point, ...]


@dataclass(frozen=True, slots=True)
class Reading:
    value: str
    quote: str


@dataclass(slots=True)
class Card:
    fields: dict[str, Points] = field(default_factory=dict[str, Points])
    readings: dict[str, Reading] = field(default_factory=dict[str, Reading])
    # What the check dropped: points with no text or with a quote not in the
    # body, and readings whose value or quote failed.
    rejected: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


def redact_card(card: Card, redact: Callable[[str], str]) -> None:
    """Replace identifying data in the card's text, quotes and rejections."""
    for name, points in card.fields.items():
        card.fields[name] = tuple(
            Point(redact(point.text), redact(point.quote)) for point in points
        )
    for name, reading in card.readings.items():
        card.readings[name] = Reading(redact(reading.value), redact(reading.quote))
    for entry in card.rejected:
        for key in ("text", "quote", "value"):
            if isinstance(entry.get(key), str) and entry[key]:
                entry[key] = redact(entry[key])


class Unreadable(Exception):
    """The reply was cut at the token cap or is not JSON. Its cost is spent."""

    def __init__(self, reason: str, usd: float) -> None:
        super().__init__(reason)
        self.usd = usd


async def write_card(
    ledger: Ledger,
    model: LanguageModel,
    card_model: str,
    body: str,
    *,
    sector: Sector,
    budget: Budget | None = None,
) -> tuple[Card, float]:
    """The checked card for `body` and what the call cost."""
    metered = await ledger.complete(
        model,
        Prompt(
            model=card_model,
            system=SYSTEMS[sector],
            text=f"Texto de la resolución:\n\n{body}",
            schema=SCHEMA,
            max_tokens=MAX_CARD_TOKENS,
            timeout_s=CARD_TIMEOUT_S,
        ),
        purpose="card",
        budget=budget,
        max_prompt_chars=MAX_CARD_PROMPT_CHARS,
    )
    if metered.completion.stop_reason == "max_tokens":
        raise Unreadable("cut at the token cap", metered.usd)
    reply = metered.completion.parsed()
    if reply is None:
        raise Unreadable("not a JSON object", metered.usd)
    return check_card(reply, body), metered.usd


def check_card(reply: dict[str, Any], body: str) -> Card:
    """Keep what the body backs word for word."""
    card = Card()
    for name in FIELDS:
        raw: Any = reply.get(name)
        entries = cast("list[Any]", raw) if isinstance(raw, list) else []
        kept: list[Point] = []
        for entry in map(_object, entries):
            text = str(entry.get("text", "")).strip()
            quote = str(entry.get("quote", "")).strip()
            if not text and not quote:
                continue
            if text and is_quoted(quote, body) and len(kept) < MAX_POINTS:
                kept.append(Point(text, quote))
            else:
                card.rejected.append({"field": name, "text": text, "quote": quote})
        if kept:
            card.fields[name] = tuple(kept)
    for name in READINGS:
        entry = _object(reply.get(name))
        value = str(entry.get("value", "")).strip()
        quote = str(entry.get("quote", "")).strip()
        if not value:
            continue
        if _valid_reading(name, value) and is_quoted(quote, body):
            card.readings[name] = Reading(value, quote)
        else:
            card.rejected.append({"reading": name, "value": value, "quote": quote})
    return card


def _valid_reading(name: str, value: str) -> bool:
    if name == "outcome":
        return value in OUTCOMES
    if name == "resolved_on":
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    return True


def _object(value: Any) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}
