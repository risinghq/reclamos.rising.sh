import io
import re
import unicodedata
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from python_calamine import CalamineWorkbook

SOURCE_URL = "https://punku.osiptel.gob.pe/Archivos/Datasets-PUNKU-OSIPTEL.zip"
FOLDER = "11. RECLAMOS DE USUARIOS - SEGUNDA INSTANCIA"
DECISIONS = "11.2."
SUBJECTS = "11.4."

Kind = Literal["RA", "RQJ"]

NUMBER = "Nro Expediente"
KIND = "Recurso/Tipo de expediente"
RESOLVED = "Fecha Expedición"
DECISION_COLUMNS = (NUMBER, KIND, RESOLVED, "Sentido", "Empresa")
SUBJECT_COLUMNS = (NUMBER, KIND, "Concepto", "Subconcepto")

_FILE = re.compile(
    r"(\d+)\s*-\s*(\d{4})\s*/\s*TRASU\s*/\s*-?\s*ST\s*-?\s*(RQJ|RA)\b", re.IGNORECASE
)
_CUT = re.compile(
    r"fecha de corte de la informaci[oó]n\s*:\s*"
    r"(\d{1,2})\s+(?:de\s+)?([a-z]+)\s+(?:de(?:l)?\s+)?(\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

type Cell = object


@dataclass(frozen=True, slots=True)
class FileKey:
    number: int
    year: int
    kind: Kind


@dataclass(frozen=True, slots=True)
class Decision:
    file: FileKey
    resolved_on: date
    sentido: str
    company: str


@dataclass(frozen=True, slots=True)
class Subject:
    file: FileKey
    concepto: str
    subconcepto: str


@dataclass(slots=True)
class Workbooks:
    decisions: list[Decision]
    subjects: list[Subject]
    cut_on: date


class SourceError(Exception):
    pass


def file_key(expediente: str) -> FileKey | None:
    found = _FILE.search(expediente)
    if found is None:
        return None
    number, year, kind = found.groups()
    return FileKey(int(number), int(year), "RQJ" if kind.upper() == "RQJ" else "RA")


def plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.upper())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s*/\s*", "/", " ".join(bare.split()))


def read_zip(path: Path) -> Workbooks:
    with zipfile.ZipFile(path) as archive:
        decision_rows, decision_notes = _sheets(
            _workbook(archive, DECISIONS), DECISION_COLUMNS
        )
        subject_rows, subject_notes = _sheets(
            _workbook(archive, SUBJECTS), SUBJECT_COLUMNS
        )
    decisions = [
        Decision(
            _key(number, kind),
            _date(resolved),
            _words(sentido).upper(),
            _words(company),
        )
        for number, kind, resolved, sentido, company in decision_rows
    ]
    subjects = [
        Subject(_key(number, kind), _words(concepto), _words(subconcepto))
        for number, kind, concepto, subconcepto in subject_rows
    ]
    if not decisions or not subjects:
        raise SourceError(f"{FOLDER} holds no {DECISIONS} or no {SUBJECTS} rows")
    cut_on = _cut_date([*decision_notes, *subject_notes])
    if cut_on is None:
        raise SourceError("no sheet states the cut date (Fecha de corte)")
    return Workbooks(decisions, subjects, cut_on)


def _workbook(archive: zipfile.ZipFile, prefix: str) -> CalamineWorkbook:
    names = [
        name
        for name in archive.namelist()
        if f"/{FOLDER}/" in f"/{name}"
        and Path(name).name.startswith(prefix)
        and name.endswith(".xlsx")
    ]
    if len(names) != 1:
        raise SourceError(f"expected one {prefix} workbook in {FOLDER}, found {names}")
    return CalamineWorkbook.from_filelike(io.BytesIO(archive.read(names[0])))


def _sheets(
    book: CalamineWorkbook, columns: Sequence[str]
) -> tuple[list[tuple[Cell, ...]], list[str]]:
    rows: list[tuple[Cell, ...]] = []
    notes: list[str] = []
    for name in book.sheet_names:
        found = _table(book, name, columns)
        if found is None:
            notes.extend(
                str(cell)
                for row in book.get_sheet_by_name(name).iter_rows()
                for cell in row
            )
        else:
            rows.extend(found)
    return rows, notes


def _table(
    book: CalamineWorkbook, name: str, columns: Sequence[str]
) -> list[tuple[Cell, ...]] | None:
    rows = book.get_sheet_by_name(name).iter_rows()
    positions = _header(rows, columns)
    if positions is None:
        return None
    return [
        cells
        for row in rows
        if str(
            (cells := tuple(row[i] if i < len(row) else "" for i in positions))[0]
        ).strip()
    ]


def _header(rows: Iterator[Sequence[Cell]], columns: Sequence[str]) -> list[int] | None:
    for row in rows:
        labels = [str(cell).strip() for cell in row]
        if all(column in labels for column in columns):
            return [labels.index(column) for column in columns]
    return None


def _key(number: Cell, kind: Cell) -> FileKey:
    key = file_key(str(number))
    if key is None or key.kind != str(kind).strip().upper():
        raise SourceError(f"unreadable file number {number!r} of type {kind!r}")
    return key


def _date(cell: Cell) -> date:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    raise SourceError(f"unreadable date {cell!r}")


def _words(cell: Cell) -> str:
    return " ".join(str(cell).split())


def _cut_date(notes: list[str]) -> date | None:
    for note in notes:
        found = _CUT.search(note)
        if found is not None and found.group(2).lower() in _MONTHS:
            day, month, year = found.groups()
            return date(int(year), _MONTHS[month.lower()], int(day))
    return None
