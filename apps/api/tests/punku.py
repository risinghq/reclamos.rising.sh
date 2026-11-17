import io
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from reclamos_api.outcomes.source import FOLDER

DECISION_HEADER = (
    "Nro Expediente",
    "Recurso/Tipo de expediente",
    "Fecha Expedición",
    "Sentido",
    "Empresa",
    "Departamento",
)
SUBJECT_HEADER = (
    "Nro Expediente",
    "Recurso/Tipo de expediente",
    "Servicio Especifico",
    "Concepto",
    "Subconcepto",
    "Fecha Expedición",
)
CUT_NOTE = "Fecha de corte de la información:24 julio de 2026"

type Row = tuple[str | date, ...]


def expediente(number: int, year: int, kind: str) -> str:
    return f"{number:07d}-{year}/TRASU/ST-{kind}"


def decision(
    number: int, year: int, kind: str, on: date, sentido: str, company: str
) -> Row:
    return (expediente(number, year, kind), kind, on, sentido, company, "LIMA")


def subject(
    number: int, year: int, kind: str, concepto: str, subconcepto: str, on: date
) -> Row:
    return (
        expediente(number, year, kind),
        kind,
        "TELEFONÍA MÓVIL",
        concepto,
        subconcepto,
        on,
    )


def write_zip(
    path: Path,
    decisions: Sequence[Sequence[Row]],
    subjects: Sequence[Sequence[Row]],
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, header, sheets, note in (
            (
                "11.2. EXPEDIENTES RESUELTOS - TRASU.xlsx",
                DECISION_HEADER,
                decisions,
                None,
            ),
            (
                "11.4. EXPEDIENTES RESUELTOS POR MATERIA Y SERVICIO - TRASU.xlsx",
                SUBJECT_HEADER,
                subjects,
                CUT_NOTE,
            ),
        ):
            archive.writestr(
                f"Datasets-PUNKU-OSIPTEL/{FOLDER}/{name}",
                _workbook(header, sheets, note),
            )
    return path


def _workbook(header: Row, sheets: Sequence[Sequence[Row]], note: str | None) -> bytes:
    book = Workbook()
    first = book.active
    assert first is not None
    book.remove(first)
    for index, rows in enumerate(sheets):
        sheet = book.create_sheet(f"DATA_{index}")
        if index == 0:
            sheet.append(("DATASET: EXPEDIENTES RESUELTOS",))
            sheet.append(())
            lead: Row = ()
        else:
            lead = ("",)
        for row in (header, *rows):
            sheet.append((*lead, *row))
    if note is not None:
        dictionary = book.create_sheet("Diccionario")
        dictionary.append(("Campo", "Descripción"))
        dictionary.append((note,))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
