from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from reclamos_api.corpus.sources import Sector

Kind = Literal[
    "precedente", "lineamiento", "reglamento", "condiciones", "modificatoria"
]


@dataclass(frozen=True, slots=True)
class Changes:
    modifies: tuple[str, ...] = ()
    incorporates: tuple[str, ...] = ()
    repeals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuleSource:
    slug: str
    title: str
    kind: Kind
    approved_by: str
    text_date: date
    pdf_url: str
    changes: Changes = field(default_factory=Changes)
    base_slug: str | None = None
    effective_on: date | None = None
    expediente: str | None = None
    visitor_searchable: bool = True
    gazette: bool = False
    text_anchor: str | None = None
    body_label: str | None = None
    sector: Sector = "telecom"


SOURCES = (
    RuleSource(
        "lineamientos-apelaciones-2021",
        "Lineamientos en materia de apelaciones",
        "lineamiento",
        "Res. 00002-2021-TRASU/SP/OSIPTEL",
        date(2021, 8, 17),
        "https://www.osiptel.gob.pe/media/wsmf0s1y/resol002-2021-trasu-sp-lineamientos-apelaciones.pdf",
    ),
    RuleSource(
        "lineamientos-quejas-2021",
        "Lineamientos en materia de quejas",
        "lineamiento",
        "Res. 00001-2021-TRASU/SP/OSIPTEL",
        date(2021, 8, 17),
        "https://www.osiptel.gob.pe/media/uiuegsd0/resol001-2021-trasu-sp-lineamientos-materia-quejas.pdf",
    ),
    RuleSource(
        "reglamento-reclamos-2022",
        "TUO del Reglamento de Reclamos",
        "reglamento",
        "Res. 099-2022-CD/OSIPTEL",
        date(2026, 8, 4),
        "https://cdn.www.gob.pe/uploads/document/file/10406777/3737345-iii-texto-unico-ordenado-del-reglamento-para-la-atencion-de-gestiones-y-reclamos-de-usuarios.pdf?v=1785944798",
    ),
    RuleSource(
        "reglamento-reclamos-129-2026",
        "Modificación del TUO del Reglamento de Reclamos",
        "modificatoria",
        "Res. 000129-2026-CD/OSIPTEL",
        date(2026, 10, 3),
        "https://www.osiptel.gob.pe/media/ddvjnqt1/resol129-2026-cd-norma-que-modifica-el-texto-unico-ordenado-del-reglamento-para-la-atencion-de-gestiones-y-reclamos-de-usuarios.pdf",
        Changes(
            modifies=(
                "Artículo 11",
                "Artículo 14",
                "Artículo 25",
                "Artículo 29",
                "Artículo 30",
                "Artículo 36",
                "Artículo 41",
                "Artículo 48",
                "Artículo 49",
                "Artículo 50",
                "Artículo 58",
                "Artículo 70",
                "Artículo 80",
                "Artículo 84",
                "Artículo 96",
                "Artículo 99",
                "Artículo 100",
                "Artículo 103",
                "Artículo 104",
                "Anexo 2",
                "Anexo 5",
            ),
            incorporates=(
                "Artículo 19-A",
                "Artículo 25-A",
                "Artículo 25-B",
                "Artículo 84-A",
                "Novena Disposición Complementaria Final",
            ),
            repeals=(
                "Artículo 83",
                "Artículo 85",
                "Artículo 86",
                "Artículo 87",
                "Artículo 88",
                "Anexo 1",
            ),
        ),
        "reglamento-reclamos-2022",
        date(2026, 10, 4),
    ),
    RuleSource(
        "condiciones-uso-2025",
        "Norma de las Condiciones de Uso",
        "condiciones",
        "Res. 132-2025-CD/OSIPTEL",
        date(2026, 7, 15),
        "https://cdn.www.gob.pe/uploads/document/file/10406564/7552617-i-norma-de-las-condiciones-de-uso%282%29.pdf?v=1792531883",
        effective_on=date(2026, 6, 27),
    ),
    RuleSource(
        "precedente-ta-072-2025",
        "Precedentes de observancia obligatoria en materia administrativa sancionadora",
        "precedente",
        "Res. 072-2025-TA/OSIPTEL",
        date(2025, 5, 14),
        "https://www.osiptel.gob.pe/media/zlymn515/resol072-2025-ta.pdf",
        visitor_searchable=False,
    ),
    RuleSource(
        "precedente-32112-2019",
        "Precedente, Exp. 32112-2019/TRASU/ST-RA",
        "precedente",
        "Res. 0064487-2020-TRASU/OSIPTEL",
        date(2020, 6, 19),
        "https://www.osiptel.gob.pe/media/arhifznq/resol1-exp32112-2019-trasu.pdf",
        expediente="32112-2019/TRASU/ST-RA",
    ),
    RuleSource(
        "precedente-02674-2015",
        "Precedente, Exp. 02674-2015/TRASU/ST-RQJ",
        "precedente",
        "Res. 1, Exp. 02674-2015/TRASU/ST-RQJ",
        date(2015, 4, 14),
        "https://www.osiptel.gob.pe/media/nstp3sop/expedienten-02674-2015-trasu-st-rqj-queja.pdf",
        expediente="02674-2015/TRASU/ST-RQJ",
        gazette=True,
    ),
    RuleSource(
        "precedente-382-2007",
        "Precedente, Exp. 382-2007/TRASU/GUS-RA",
        "precedente",
        "Res. 2, Exp. 382-2007/TRASU/GUS-RA",
        date(2007, 3, 15),
        "https://www.osiptel.gob.pe/media/5kdccrzq/expedienten%C2%BA-382-2007-trasu-gus-ra-recursoapelacion.pdf",
        expediente="382-2007/TRASU/GUS-RA",
        gazette=True,
    ),
    RuleSource(
        "precedente-12957-2005",
        "Precedente, Exp. 12957-2005/TRASU/GUS-RA",
        "precedente",
        "Res. 2, Exp. 12957-2005/TRASU/GUS-RA",
        date(2006, 1, 19),
        "https://www.osiptel.gob.pe/media/fd5hslgr/expedienten%C2%BA-12957-2005-trasu-gus-ra-recursoapelacion.pdf",
        expediente="12957-2005/TRASU/GUS-RA",
        gazette=True,
    ),
    RuleSource(
        "precedente-06982-2003",
        "Precedente, Exp. 06982-2003/TRASU/GUS-RQJ",
        "precedente",
        "Res. 1, Exp. 06982-2003/TRASU/GUS-RQJ",
        date(2004, 9, 14),
        "https://www.osiptel.gob.pe/media/cozlo2ql/expediente-n%C2%BA-06982-2003-trasu-gus-rqj-2.pdf",
        expediente="06982-2003/TRASU/GUS-RQJ",
        gazette=True,
    ),
    RuleSource(
        "precedente-07837-2003",
        "Precedente, Exp. 07837-2003/TRASU/GUS-RQJ",
        "precedente",
        "Res. 1, Exp. 07837-2003/TRASU/GUS-RQJ",
        date(2003, 12, 30),
        "https://www.osiptel.gob.pe/media/dgdg0b4z/expedienten%C2%BA-07837-2003-trasu-gus-rqj-queja.pdf",
        expediente="07837-2003/TRASU/GUS-RQJ",
        gazette=True,
    ),
    RuleSource(
        "reclamos-electricidad-gas-2014",
        "Procedimiento Administrativo de Reclamos de los Usuarios de los "
        "Servicios Públicos de Electricidad y Gas Natural",
        "reglamento",
        "Res. 269-2014-OS/CD",
        date(2014, 12, 29),
        "https://www.osinergmin.gob.pe/seccion/centro_documental/PlantillaMarcoLegalBusqueda/OSINERGMIN%20No.269-2014-OS-CD.pdf",
        effective_on=date(2015, 5, 23),
        text_anchor=r"art.culo\s+1\s*\.\-\s*objetivo",
        sector="energy",
    ),
    # Res. 014-2025-OS/CD changes numerals inside articles 2 and 39 and Anexo I,
    # which article-level consolidation cannot merge without losing the rest of
    # each article. It stays recorded and is not applied.
    RuleSource(
        "reclamos-electricidad-gas-014-2025",
        "Modificación de la Directiva de Reclamos",
        "modificatoria",
        "Res. 014-2025-OS/CD",
        date(2025, 2, 6),
        "https://cdn.www.gob.pe/uploads/document/file/8630527/7148393-resolucion-de-consejo-directivo-organismo-supervisor-de-la-inversion-en-energia-y-mineria-osinergmin-n-014-2025-os-cd.pdf",
        base_slug="reclamos-electricidad-gas-2014",
        effective_on=date(2025, 2, 7),
        sector="energy",
    ),
    RuleSource(
        "lineamientos-jaru-i",
        "Lineamientos resolutivos de la JARU, parte I",
        "lineamiento",
        "JARU, Sala Plena",
        date(2025, 4, 23),
        "https://cdn.www.gob.pe/uploads/document/file/7977495/6707803-parte-i-de-los-lineamientos-resolutivos-de-la-jaru.pdf",
        body_label="Lineamiento",
        sector="energy",
    ),
    RuleSource(
        "lineamientos-jaru-ii",
        "Lineamientos resolutivos de la JARU, parte II",
        "lineamiento",
        "JARU, Sala Plena",
        date(2025, 4, 23),
        "https://cdn.www.gob.pe/uploads/document/file/7977496/6707803-parte-ii-de-los-lineamientos-resolutivos-de-la-jaru.pdf",
        body_label="Lineamiento",
        sector="energy",
    ),
    RuleSource(
        "precedentes-jaru",
        "Compendio de precedentes de observancia obligatoria de la JARU",
        "precedente",
        "JARU",
        date(2024, 12, 18),
        "https://cdn.www.gob.pe/uploads/document/file/7389465/6301997-jaru-compendio-precedentes.pdf",
        body_label="Precedente",
        sector="energy",
    ),
)
