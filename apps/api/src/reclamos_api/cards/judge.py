"""Judge whether each point of a card says only what its quote says.

The quotes passed the check against the body, so a point its quote backs is
backed by the resolution. The judge reads the points and their quotes only,
not the whole body.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, cast

from reclamos_api.cards.card import FIELDS, Points
from reclamos_api.corpus.sources import Sector
from reclamos_api.llm.client import LanguageModel, Prompt
from reclamos_api.llm.spend import Budget, Ledger

MAX_JUDGE_TOKENS = 1_000

SYSTEM = """\
Revisas fichas escritas a partir de resoluciones del TRASU de OSIPTEL.

Cada campo de la ficha tiene puntos numerados. Un punto es una oración y la \
cita de la resolución que la respalda. Los campos son:
- claim: qué reclamó el usuario y qué pidió.
- operator_position: qué dijo o decidió la empresa operadora antes de la \
apelación o la queja.
- reasoning: por qué el tribunal decidió lo que decidió.
- evidence: la prueba que decidió el caso, o la prueba que faltó.
- orders: qué ordenó o declaró el tribunal en la parte resolutiva.

Un punto es fiel cuando todo lo que afirma su oración está en su propia cita \
y lo atribuye a quien lo dijo en ella: el usuario, la empresa o el tribunal. \
Otra cita no lo respalda. Conocimiento que no está en la cita tampoco, aunque \
sea cierto. Decir lo mismo con otras palabras, más corto o más sencillo, sí \
es fiel. Omitir detalles de la cita también es fiel.

En "unsupported" pon solo los puntos que no son fieles: el campo, su número y \
en "claim" las palabras de la oración, copiadas tal cual, que su cita no \
respalda. Un punto que su cita respalda no va en la lista, ni siquiera con \
una nota. Si todos son fieles, deja "unsupported" vacío. Escribe en español.
"""

# The energy judge reads the same fields and the same rule of faithfulness;
# it names the JARU and the "empresa concesionaria o distribuidora".
ENERGY_SYSTEM = """\
Revisas fichas escritas a partir de resoluciones de la JARU de Osinergmin.

Cada campo de la ficha tiene puntos numerados. Un punto es una oración y la \
cita de la resolución que la respalda. Los campos son:
- claim: qué reclamó el usuario y qué pidió.
- operator_position: qué dijo o decidió la empresa concesionaria o \
distribuidora antes de la apelación o la queja.
- reasoning: por qué el tribunal decidió lo que decidió.
- evidence: la prueba que decidió el caso, o la prueba que faltó.
- orders: qué ordenó o declaró el tribunal en la parte resolutiva.

Un punto es fiel cuando todo lo que afirma su oración está en su propia cita \
y lo atribuye a quien lo dijo en ella: el usuario, la empresa o el tribunal. \
Otra cita no lo respalda. Conocimiento que no está en la cita tampoco, aunque \
sea cierto. Decir lo mismo con otras palabras, más corto o más sencillo, sí \
es fiel. Omitir detalles de la cita también es fiel.

En "unsupported" pon solo los puntos que no son fieles: el campo, su número y \
en "claim" las palabras de la oración, copiadas tal cual, que su cita no \
respalda. Un punto que su cita respalda no va en la lista, ni siquiera con \
una nota. Si todos son fieles, deja "unsupported" vacío. Escribe en español.
"""

SYSTEMS: dict[Sector, str] = {"telecom": SYSTEM, "energy": ENERGY_SYSTEM}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "unsupported": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": list(FIELDS)},
                    "point": {"type": "integer"},
                    "claim": {"type": "string"},
                },
                "required": ["field", "point", "claim"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["unsupported"],
    "additionalProperties": False,
}

# A verdict given with another prompt or schema is out of date. Each sector
# versions its own prompt, so a change to one makes only its verdicts stale.
JUDGE_VERSIONS = {
    sector: hashlib.sha256(
        (system + json.dumps(SCHEMA, sort_keys=True)).encode()
    ).hexdigest()[:12]
    for sector, system in SYSTEMS.items()
}


@dataclass(frozen=True, slots=True)
class CardVerdict:
    # Each point the judge found unsupported: its field, its number counted
    # from 1, and the claim its quote does not back. None when the judge's
    # reply could not be read.
    unsupported: list[dict[str, Any]] | None
    usd: float


async def judge_card(
    ledger: Ledger,
    model: LanguageModel,
    judge_model: str,
    fields: dict[str, Points],
    *,
    sector: Sector,
    budget: Budget | None = None,
) -> CardVerdict:
    metered = await ledger.complete(
        model,
        Prompt(
            model=judge_model,
            system=SYSTEMS[sector],
            text=card_text(fields),
            schema=SCHEMA,
            max_tokens=MAX_JUDGE_TOKENS,
        ),
        purpose="judge",
        budget=budget,
    )
    reply = metered.completion.parsed()
    items: Any = None if reply is None else reply.get("unsupported")
    if metered.completion.stop_reason == "max_tokens" or not isinstance(items, list):
        return CardVerdict(None, metered.usd)
    entries = [
        cast("dict[str, Any]", item)
        for item in cast("list[Any]", items)
        if isinstance(item, dict)
    ]
    unsupported = [
        {
            "field": str(entry.get("field", "")),
            "point": entry.get("point"),
            "claim": str(entry.get("claim", "")),
        }
        for entry in entries
    ]
    return CardVerdict(unsupported, metered.usd)


def card_text(fields: dict[str, Points]) -> str:
    blocks: list[str] = []
    for name in FIELDS:
        for number, point in enumerate(fields.get(name, ()), start=1):
            blocks.append(f"{name} {number}: {point.text}\nCita: «{point.quote}»")
    return "\n\n".join(blocks)
