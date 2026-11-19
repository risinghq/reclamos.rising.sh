"""The collections a crawl reads, and what each one's entries are.

Every source declares its sector, its regulator, its tribunal and the pattern
of the expediente numbers its tribunal issues. The Osinergmin collection mixes
JARU resolutions — appeals of user complaints, which the corpus keeps — with
resolutions of the Cuerpos Colegiados and the Tribunal de Solución de
Controversias, which decide disputes between companies. A skipped entry is
recorded with the reason, so `corpus stats` counts it.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

SECTORS = ("telecom", "energy")
Sector = Literal["telecom", "energy"]

# A listing title is "Expediente N.° " before the expediente number, and older
# titles repeat the word: "Expediente N.° Expediente 03779-2006/TRASU/GUS-RA".
_EXPEDIENTE_LABEL = re.compile(r"^(?:expediente\s*(?:n\.?\s*[°º]\s*)?)+", re.I)

# Osinergmin titles are "Resolución Administrativa N.° 5981-2024 OS/JARU-S2"
# for JARU, "Resolución del Cuerpo Colegiado N.° 004-2004-OS/CC-13" for the
# Cuerpos Colegiados and "Resolución del Tribunal de Solución de Controversias
# N.° 004-2003-OS/TSC-03" for the TSC.
_RESOLUCION_LABEL = re.compile(
    r"^resoluci.n\s+(?:administrativa|del\s+cuerpo\s+colegiado|"
    r"del\s+tribunal\s+de\s+soluci.n\s+de\s+controversias)\s*(?:n\.?\s*[°º]\s*)?",
    re.I,
)

_JARU = re.compile(r"(\d{1,6})\s*-\s*(\d{4})\s*-?\s*OS\s*/\s*JARU\s*-\s*(S\w+)", re.I)
_CC = re.compile(r"OS\s*-\s*CC\b|/CC\s*-", re.I)
_TSC = re.compile(r"OS\s*[-/]\s*TSC\b|TSC\s*-\s*\w+", re.I)


def _jaru(expediente: str) -> str | None:
    match = _JARU.search(expediente)
    if match is None:
        return None
    return f"{match[1]}-{match[2]}-OS/JARU-{match[3].upper()}"


def _osinergmin_skip(expediente: str) -> str | None:
    if _jaru(expediente) is not None:
        return None
    if _CC.search(expediente):
        return "cuerpo_colegiado"
    if _TSC.search(expediente):
        return "tribunal_controversias"
    return "not_jaru"


def _everything(_: str) -> str | None:
    return None


def _jaru_or_bare(expediente: str) -> str:
    return _jaru(expediente) or expediente


@dataclass(frozen=True, slots=True)
class Source:
    slug: str
    sector: Sector
    regulator: str
    tribunal: str
    collection_url: str
    label: re.Pattern[str]
    normalize: Callable[[str], str]
    skip: Callable[[str], str | None]

    def expediente(self, title: str) -> str:
        """The bare expediente the listing title names."""
        return self.label.sub("", title).strip()

    def keep(self, expediente: str) -> str:
        """The expediente as it is stored. JARU numbers are normalized to
        `NNNN-YYYY-OS/JARU-SX`."""
        return self.normalize(expediente)


OSIPTEL = Source(
    slug="osiptel",
    sector="telecom",
    regulator="OSIPTEL",
    tribunal="TRASU",
    collection_url="https://www.gob.pe/institucion/osiptel/colecciones/52616-jurisprudencia",
    label=_EXPEDIENTE_LABEL,
    normalize=lambda expediente: expediente,
    skip=_everything,
)

OSINERGMIN = Source(
    slug="osinergmin",
    sector="energy",
    regulator="OSINERGMIN",
    tribunal="JARU",
    collection_url="https://www.gob.pe/institucion/osinergmin/colecciones/837",
    label=_RESOLUCION_LABEL,
    normalize=_jaru_or_bare,
    skip=_osinergmin_skip,
)

SOURCES = (OSIPTEL, OSINERGMIN)
SOURCE_BY_SLUG = {source.slug: source for source in SOURCES}
