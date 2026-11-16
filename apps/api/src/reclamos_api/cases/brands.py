"""The brands visitors know, and the legal names parse reads from resolutions.

A resolution names the company that answered the claim, so a merged or renamed
company keeps its old name: TIM and Telmex became Claro, Nextel became Entel,
Telefónica del Perú became Integratel and still sells as Movistar.
"""

import re
import unicodedata

BRANDS: dict[str, tuple[str, ...]] = {
    "Claro": ("AMERICA MOVIL PERU S.A.C.", "TIM PERU S.A.C.", "TELMEX PERU S.A."),
    "Movistar": (
        "TELEFONICA DEL PERU S.A.A.",
        "TELEFONICA MOVILES S.A.",
        "TELEFONICA MULTIMEDIA S.A.C.",
        "TELEFONICA MULTIMEDIA S.A.",
        "TELEFONICA EMPRESAS PERU S.A.A.",
        "INTEGRATEL PERU S.A.A.",
    ),
    "Entel": ("ENTEL PERU S.A.", "NEXTEL DEL PERU S.A."),
    "Bitel": ("VIETTEL PERU S.A.C.",),
    "WOW": ("WOW TEL S.A.C.",),
    "Win": ("WIN NET - TELECOM S.A.C.",),
    "DirecTV": ("DIRECTV PERU S.R.L.",),
    "Americatel": ("AMERICATEL PERU S.A.",),
}

# The words a visitor writes for each brand, without accents. "claro" is also a
# common word, so "me quedó claro" leans the results toward Claro. Claro is
# behind a third of the corpus, so that lean costs little.
_WORDS: dict[str, tuple[str, ...]] = {
    "Claro": ("claro", "america movil", "tim", "telmex"),
    "Movistar": ("movistar", "telefonica", "integratel"),
    "Entel": ("entel", "nextel"),
    "Bitel": ("bitel", "viettel"),
    "WOW": ("wow",),
    "Win": ("win",),
    "DirecTV": ("directv", "direct tv"),
    "Americatel": ("americatel",),
}

_PATTERNS = {
    brand: re.compile(r"\b(?:" + "|".join(map(re.escape, words)) + r")\b")
    for brand, words in _WORDS.items()
}

_BRAND_OF = {name: brand for brand, names in BRANDS.items() for name in names}


def brand_of(operator: str | None) -> str | None:
    """The brand that sells as `operator`, a legal name as parse reads it."""
    return _BRAND_OF.get(operator) if operator else None


def brands_named(text: str) -> list[str]:
    """The brands `text` names, in the order of `BRANDS`."""
    plain = _plain(text)
    return [brand for brand, pattern in _PATTERNS.items() if pattern.search(plain)]


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
