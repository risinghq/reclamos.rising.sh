"""Which sector a visitor's question is about.

The web app does not ask the visitor to pick a sector: a visitor describes a
problem, and a question about an electricity bill should not have to know that
electricity belongs to another regulator. The words below name the service or
its companies; a word both sectors use, such as "línea" or "facturación", is
left out on purpose. When the question names words of both sectors, or of
neither, no sector filter applies.
"""

import re
import unicodedata

_WORDS: dict[str, tuple[str, ...]] = {
    "energy": (
        "luz",
        "electricidad",
        "electrocentro",
        "electronoroeste",
        "medidor",
        "kwh",
        "voltaje",
        "tension",
        "energia",
        "gas",
        "suministro",
        "acometida",
        "calidda",
        "quavii",
        "contugas",
        "enel",
        "pluz",
        "hidrandina",
        "seal",
        "osinergmin",
        "jaru",
    ),
    "telecom": (
        "telefono",
        "celular",
        "internet",
        "cable",
        "portabilidad",
        "fibra",
        "wifi",
        "megas",
        "recarga",
        "roaming",
        "llamada",
        "sms",
        "claro",
        "movistar",
        "entel",
        "bitel",
        "telefonica",
        "integratel",
        "directv",
        "osiptel",
        "trasu",
    ),
}

_PATTERNS = {
    sector: re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b")
    for sector, words in _WORDS.items()
}


def sector_of(query: str) -> str | None:
    """The sector `query` is about, or None when the words name both sectors or
    neither."""
    plain = _plain(query)
    found = [sector for sector, pattern in _PATTERNS.items() if pattern.search(plain)]
    return found[0] if len(found) == 1 else None


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
