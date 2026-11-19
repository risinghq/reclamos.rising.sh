import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from itertools import pairwise
from typing import Any

import httpx

from reclamos_api.corpus.extract import OCR_DPI, OCR_PAGE_SEGMENTATION, extract_text
from reclamos_api.corpus.redact import REDACTOR_VERSION, Redactor
from reclamos_api.corpus.repository import vector_literal
from reclamos_api.corpus.store import ObjectStore
from reclamos_api.retrieval.embedder import Embedder
from reclamos_api.rules.sources import SOURCES, Changes, RuleSource

RULES_VERSION = "5"
GAZETTE_OCR_DPI = 300
GAZETTE_OCR_PAGE_SEGMENTATION = "3"
PASSAGE_MAXIMUM = 1200
Download = Callable[[str], Awaitable[bytes]]


class ConsolidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Part:
    label: str
    text: str
    origin: "TextOrigin"


@dataclass(frozen=True, slots=True)
class TextOrigin:
    approved_by: str
    text_date: date
    pdf_url: str


@dataclass(frozen=True, slots=True)
class ServedPart:
    label: str
    text: str
    origin: TextOrigin


_HEADING = re.compile(
    r'^\s*(?P<quote>["“])?(?P<heading>(?:art[ií]?culo\s+\d+(?:-\s*[a-z])?\s*\.\s*\-|'
    r"(?:primera|segunda|tercera|cuarta|quinta|sexta|s[eé]ptima|octava|novena)"
    r"(?:\s+disposici[oó]n\s+complementaria\s+(?:final|transitoria)|\s*\.\s*\-)|"
    r"anexo\s*(?:n[°ºo.]?\s*)?\d+)[^\n]*)",
    re.IGNORECASE | re.MULTILINE,
)
_SPIJ_NOTE = re.compile(
    r"\(\s*\*+\s*\)(?:(?!\(\s*\*+\s*\)).)*?"
    r"(?P<action>modificad[oa]|derogad[oa]).*?"
    r"Resoluci[oó]n\s*N[°ºo.]?\s*(?P<norm>[^,\n]+?(?:-\s*\n\s*[^,\n]+)*)"
    r"(?=\s*,\s*publicada|\s*$)"
    r"(?:\s*,\s*publicada\s+el\s+(?P<published>[^,:\n]+))?"
    r"(?P<replacement>.*?cuyo\s+texto\s+es\s+el\s+siguiente\s*:?)?",
    re.IGNORECASE | re.DOTALL,
)
_SPIJ_MARKER = re.compile(
    r"\(\s*\*+\s*\)(?:(?!\(\s*\*+\s*\)).)*?(?:modificad[oa]|derogad[oa])",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_NOTE = re.compile(r"[íi]tem\s+(?P<number>\d+)\s+modificad", re.IGNORECASE)
_SPANISH_DATE = re.compile(
    r"(?P<day>\d{1,2})\s+(?:de\s+)?(?P<month>[a-záéíóú]+)\s+(?:de\s+)?(?P<year>\d{4})",
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
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_FIRST_ARTICLE = re.compile(
    r'^\s*["“]?art[ií]?culo\s+1\s*\.\-', re.IGNORECASE | re.MULTILINE
)
_LINKED_ANNEXES = re.compile(
    r"anexos?\s*(?:n[°ºo.]?s?\.?\s*)?(?P<first>\d+)\s+al\s+(?P<last>\d+)",
    re.IGNORECASE,
)
_BROKEN_DE = re.compile(
    r"\b(?P<word>[A-Za-zÁÉÍÓÚÜáéíóúüÑñ]+(?:ción|sión|dad|tad|miento|mento|encia|"
    r"ancia|ario|aria|ible|ables|ados))de(?=\s)",
)
_PAGE_FOOTER = re.compile(r"(?m)^\s*\d+\s*\|\s*\d+\s*$")
_SIGNATURE_SIGNER = re.compile(
    r"firmado\s+digitalmente\s+por\b[\s\S]{0,200}?\bFAU\s+\d+\s+(?:soft|hard)\b",
    re.IGNORECASE,
)
_SIGNATURE_REASON = re.compile(r"motivo\s*:\s*Doy\s+V[°ºo]\s*B[°ºo]", re.IGNORECASE)
_SIGNATURE_DATE = re.compile(
    r"fecha\s*:\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\s+\d{1,2}:\d{2}(?::\d{2})?"
    r"\s*[+-]\d{2}:?\d{2}",
    re.IGNORECASE,
)
_LEADING_QUOTE = re.compile(
    r'(?im)^\s*["“”]\s*(?=(?:art[ií]?culo\s+\d+\s*\.\s*-|sumilla\s*:|\d+(?:\.\d+)*\.\s))'
)
_STRUCTURAL_HEADING = re.compile(
    r"(?im)^\s*(?:(?:sub\s*[-\u2013]?\s*)?cap[ií]tulo|t[ií]tulo)\b"
)
_SUMILLA = re.compile(r"(?im)^\s*sumilla\s*:")
_PRECEDENT_CRITERION = re.compile(
    r"(?is)(?:(?:corresponde\s+declarar|se\s+declara|declarar|señala|"
    r"se\s+establece)[^.]*?)?precedente\s+de\s+observancia\s+obligatoria[^.]*\."
)
_GAZETTE_HEADER = re.compile(
    r"(?im)^\s*(?:Lima,\s*[^\n]+|(?:P[áa]g\.\s*\d+\s+)?El\s+Per(?:u|i)ano|"
    r"P[áa]g\.\s*\d+)\s*$\n?"
)
_GAZETTE_OSIPTEL = re.compile(r"(?im)^\s*OSIPTEL\s*$")
_GAZETTE_SIGNATURE = re.compile(
    r"(?is)presidente\s+del\s+tribunal\s+(?:administrativo\s+de\s+)?"
    r"soluci[oó]n\s+de\s+reclamos(?:\s+de\s+usuarios)?"
)
_GAZETTE_VOCALES = re.compile(r"(?im)^\s*con\s+la\s+intervenci[oó]n\s+de")
_LINEAMIENTO_HEADING = re.compile(
    r"(?m)^\s*(?P<number>(?:\d+(?:\.\d+)*|[IVXLCDM]+))\.\s+"
    r"(?=[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9 ,;:()'\"./\u2013\u2014-]*\s*$)"
)
_ITEM_START = re.compile(r"(?m)^\s*(?=(?:\d+(?:\.\d+)*|[A-Za-z])(?:[.)])\s+)")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")


def _label(heading: str) -> str:
    plain = " ".join(heading.replace("\n", " ").split())
    article = re.match(r"(?i)art[ií]?culo\s+(\d+(?:-\s*[a-z])?)", plain)
    if article:
        return f"Artículo {article.group(1).replace(' ', '').upper()}"
    annex = re.match(r"(?i)anexo\s*(?:n[°ºo.]?\s*)?(\d+)", plain)
    if annex:
        return f"Anexo {annex.group(1)}"
    final = re.match(
        r"(?i)(primera|segunda|tercera|cuarta|quinta|sexta|s[eé]ptima|octava|novena)",
        plain,
    )
    if final:
        return f"{final.group(1).capitalize()} Disposición Complementaria Final"
    return plain


def _source_origin(source: RuleSource) -> TextOrigin:
    return TextOrigin(source.approved_by, source.text_date, source.pdf_url)


def _normalise_text(text: str) -> str:
    text = _PAGE_FOOTER.sub("", text)
    text = _SIGNATURE_SIGNER.sub("", text)
    text = _SIGNATURE_REASON.sub("", text)
    text = _SIGNATURE_DATE.sub("", text)
    text = _PAGE_FOOTER.sub("", text)
    text = _LEADING_QUOTE.sub("", text)
    text = _BROKEN_DE.sub(r"\g<word> de", text)
    return text.replace("\f", " ").strip(' "“”')


def _before_structural_heading(text: str) -> str:
    heading = _STRUCTURAL_HEADING.search(text)
    return text if heading is None else text[: heading.start()]


def _served_text(text: str) -> str:
    return " ".join(_normalise_text(text).split()).strip(' "“”')


def _current_text(source: RuleSource, body: str) -> str:
    if source.kind not in ("reglamento", "condiciones"):
        return body
    first = _FIRST_ARTICLE.search(body)
    if first is None:
        raise ConsolidationError(f"{source.slug} has no first article")
    return body[first.start() :]


def _linked_annexes(body: str) -> set[str]:
    labels: set[str] = set()
    for match in _LINKED_ANNEXES.finditer(body):
        labels.update(
            f"Anexo {number}"
            for number in range(int(match["first"]), int(match["last"]) + 1)
        )
    return labels


def _note_origin(note: re.Match[str], source: RuleSource) -> TextOrigin:
    published = note["published"]
    if published is None:
        raise ConsolidationError("a SPIJ modification note names no publication date")
    matched = _SPANISH_DATE.search(published)
    if matched is None:
        raise ConsolidationError(
            f"a SPIJ note has an invalid publication date: {published}"
        )
    # OCR spaces the separators of a resolution number ("00224 -2023-CD/ OSIPTEL").
    norm = re.sub(r"\s*([-/])\s*", r"\1", note["norm"]).strip()
    return TextOrigin(
        f"Res. {norm}",
        date(
            int(matched["year"]),
            _MONTHS[matched["month"].lower()],
            int(matched["day"]),
        ),
        source.pdf_url,
    )


def _replace_item(value: str, note: re.Match[str]) -> str | None:
    item = _ITEM_NOTE.search(note[0])
    if item is None:
        return None
    number = int(item["number"])
    old = re.search(rf"(?<!\d){number}\.\s", value)
    replacement = re.search(rf"(?:[\"“]\s*)?{number}\.\s", value[note.end() :])
    if old is None or replacement is None:
        return None
    replacement_start = note.end() + replacement.start()
    next_item = re.search(
        rf"\s+(?P<number>{number + 1}|[1-9]\d{{1,}})\.\s",
        value[replacement_start + 1 :],
    )
    replacement_end = (
        replacement_start + 1 + next_item.start()
        if next_item is not None
        else len(value)
    )
    current = value[replacement_start:replacement_end].rstrip(' "”')
    return f"{value[: old.start()]}{current}{value[replacement_end:]}"


def split_parts(source: RuleSource, text: str) -> dict[str, Part]:
    text = _normalise_text(text)
    matches = [
        match
        for match in _HEADING.finditer(text)
        if not (_label(match["heading"]).startswith("Anexo") and match["quote"] is None)
    ]
    if not matches:
        raise ConsolidationError("the text has no articles, dispositions or annexes")
    parts: dict[str, Part] = {}
    index = 0
    while index < len(matches):
        match = matches[index]
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = _normalise_text(
            _before_structural_heading(text[match.start() : end])
        ).strip()
        label = _label(match["heading"])
        note = _SPIJ_NOTE.search(value)
        if note is None:
            if _SPIJ_MARKER.search(value):
                raise ConsolidationError(f"{label} has a SPIJ note without a norm")
            if label in parts:
                raise ConsolidationError(f"duplicate {label} without a SPIJ note")
            parts[label] = Part(label, value, _source_origin(source))
            index += 1
            continue
        origin = _note_origin(note, source)
        if note["action"].lower().startswith("derog"):
            parts.pop(label, None)
            index += 1
            continue
        if note["replacement"] is None:
            raise ConsolidationError(f"{label} has no SPIJ replacement text")
        if index + 1 == len(matches) or _label(matches[index + 1]["heading"]) != label:
            replacement = _replace_item(value, note)
            if replacement is None:
                raise ConsolidationError(f"{label} has no SPIJ replacement article")
            parts[label] = Part(label, replacement, origin)
            index += 1
            continue
        replacement_end = (
            matches[index + 2].start() if index + 2 < len(matches) else len(text)
        )
        replacement = _normalise_text(
            _before_structural_heading(
                text[matches[index + 1].start() : replacement_end]
            )
        ).strip()
        parts[label] = Part(label, replacement, origin)
        index += 2
    return parts


def _require(parts: dict[str, Part], labels: Iterable[str], source: RuleSource) -> None:
    missing = [label for label in labels if label not in parts]
    if missing:
        names = ", ".join(missing)
        raise ConsolidationError(f"{source.slug} declares missing text: {names}")


def consolidate(
    base: RuleSource,
    body: str,
    amendments: Sequence[tuple[RuleSource, str]],
) -> list[ServedPart]:
    parts = split_parts(base, _current_text(base, body))
    linked_annexes = _linked_annexes(body)
    for source, amendment_body in sorted(
        amendments, key=lambda item: item[0].text_date
    ):
        if source.text_date <= base.text_date:
            raise ConsolidationError(
                f"{source.slug} is not later than its base text date"
            )
        changes: Changes = source.changes
        if not (changes.modifies or changes.incorporates or changes.repeals):
            continue
        amendment_parts = split_parts(source, amendment_body)
        _require(amendment_parts, changes.modifies + changes.incorporates, source)
        for label in changes.modifies + changes.repeals:
            if label in linked_annexes and label not in parts:
                parts[label] = Part(label, "", _source_origin(base))
        _require(parts, changes.modifies + changes.repeals, source)
        for label in changes.modifies + changes.incorporates:
            parts[label] = amendment_parts[label]
        for label in changes.repeals:
            del parts[label]
    return [ServedPart(label, part.text, part.origin) for label, part in parts.items()]


def split_document(source: RuleSource, body: str) -> list[ServedPart]:
    if source.kind in ("reglamento", "condiciones"):
        return _expand_parts(
            ServedPart(part.label, part.text, part.origin)
            for part in split_parts(source, _current_text(source, body)).values()
        )
    if source.kind == "lineamiento":
        headings = _lineamiento_headings(body)
        return [
            passage
            for index, heading in enumerate(headings)
            for passage in _labelled_passages(
                f"Numeral {heading['number']}",
                body[
                    heading.start() : headings[index + 1].start()
                    if index + 1 < len(headings)
                    else len(body)
                ],
                _source_origin(source),
            )
        ]
    if source.kind == "precedente":
        if source.gazette:
            body = _gazette_precedent_text(source, body)
        body = _precedent_text(body)
        label = "Sumilla" if body.lower().startswith("sumilla") else "Pasaje"
        return _labelled_passages(label, body, _source_origin(source))
    return []


def _expand_parts(parts: Iterable[ServedPart]) -> list[ServedPart]:
    return [
        passage
        for part in parts
        for passage in _labelled_passages(part.label, part.text, part.origin)
    ]


def _lineamiento_headings(body: str) -> list[re.Match[str]]:
    candidates = list(_LINEAMIENTO_HEADING.finditer(body))
    if not candidates:
        raise ConsolidationError("the lineamiento has no numbered headings")
    by_number: dict[str, list[re.Match[str]]] = {}
    for candidate in candidates:
        by_number.setdefault(candidate["number"], []).append(candidate)
    duplicates = [
        matches[-1].start() for matches in by_number.values() if len(matches) > 1
    ]
    if duplicates:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.start() >= min(duplicates)
        ]
    labels = [candidate["number"] for candidate in candidates]
    if len(labels) != len(set(labels)):
        raise ConsolidationError("the lineamiento has duplicate numbered headings")
    return candidates


def _precedent_text(body: str) -> str:
    body = _normalise_text(body)
    body = _unwrap_ocr_lines(body)
    criterion = _PRECEDENT_CRITERION.search(body)
    if criterion is not None:
        return body[criterion.start() :]
    sumilla = _SUMILLA.search(body)
    if sumilla is not None:
        return body[sumilla.start() :]
    return body


def _unwrap_ocr_lines(body: str) -> str:
    return re.sub(r"(?<!\n)\n(?!\n)", " ", body)


def _gazette_precedent_text(source: RuleSource, body: str) -> str:
    if source.expediente is None:
        raise ConsolidationError(f"{source.slug} has no expediente for gazette cut")
    body = _GAZETTE_HEADER.sub("", body)
    expediente = _expediente_pattern(source.expediente).search(body)
    if expediente is None:
        raise ConsolidationError(f"{source.slug} has no gazette expediente heading")
    before = body[: expediente.start()]
    osiptel = list(_GAZETTE_OSIPTEL.finditer(before))
    start = osiptel[-1].start() if osiptel else before.rfind("\n") + 1
    signature = _GAZETTE_SIGNATURE.search(body, expediente.end())
    if signature is None:
        raise ConsolidationError(f"{source.slug} has no gazette signature")
    precedent = body[start : signature.end()]
    vocales = _GAZETTE_VOCALES.search(precedent)
    return precedent[: vocales.start()] if vocales is not None else precedent


def _expediente_pattern(expediente: str) -> re.Pattern[str]:
    number, year, *_ = re.findall(r"\d+", expediente)
    return re.compile(
        rf"0*{re.escape(number.lstrip('0'))}\s*[-/\u2013\u2014]\s*{re.escape(year)}"
        r"(?=[^0-9]|$)(?=(?s:.{0,80}trasu))",
        re.IGNORECASE,
    )


def _labelled_passages(label: str, text: str, origin: TextOrigin) -> list[ServedPart]:
    passages = _passages(text)
    total = len(passages)
    return [
        ServedPart(
            label if total == 1 else f"{label} (parte {index} de {total})",
            passage,
            origin,
        )
        for index, passage in enumerate(passages, start=1)
    ]


def _passages(text: str, maximum: int = PASSAGE_MAXIMUM) -> list[str]:
    body = _normalise_text(text)
    boundaries = {0, len(body)}
    boundaries.update(match.end() for match in _PARAGRAPH_BREAK.finditer(body))
    boundaries.update(match.start() for match in _ITEM_START.finditer(body))
    units = [
        _served_text(body[start:end]) for start, end in pairwise(sorted(boundaries))
    ]
    passages: list[str] = []
    current = ""
    for unit in units:
        if not unit:
            continue
        for piece in _bounded_passages(unit, maximum):
            if current and len(current) + 1 + len(piece) > maximum:
                passages.append(current)
                current = piece
            elif current:
                current = f"{current} {piece}"
            else:
                current = piece
    if current:
        passages.append(current)
    return _merge_short_passages(passages, maximum)


def _merge_short_passages(passages: list[str], maximum: int) -> list[str]:
    minimum = 200
    merged: list[str] = []
    index = 0
    while index < len(passages):
        passage = passages[index]
        if len(passage) >= minimum or len(passages) == 1:
            merged.append(passage)
            index += 1
            continue
        if merged and len(merged[-1]) + 1 + len(passage) <= maximum:
            merged[-1] = f"{merged[-1]} {passage}"
            index += 1
            continue
        if merged:
            combined = f"{merged[-1]} {passage}"
            boundary = combined.rfind(" ", 0, maximum - minimum + 1)
            if boundary > 0:
                merged[-1] = combined[:boundary].rstrip()
                merged.append(combined[boundary:].lstrip())
                index += 1
                continue
        if index + 1 < len(passages):
            following = passages[index + 1]
            if len(passage) + 1 + len(following) <= maximum:
                passages[index + 1] = f"{passage} {following}"
            else:
                minimum_prefix = minimum - len(passage)
                boundary = following.find(" ", minimum_prefix)
                if boundary == -1:
                    boundary = minimum_prefix
                merged.append(f"{passage} {following[:boundary].rstrip()}")
                passages[index + 1] = following[boundary:].lstrip()
        else:
            merged.append(passage)
        index += 1
    return merged


def _bounded_passages(text: str, maximum: int) -> list[str]:
    pieces: list[str] = []
    remaining = _served_text(text)
    while len(remaining) > maximum:
        boundaries = [
            match.end()
            for match in re.finditer(r"(?<=[.;:])\s+", remaining[: maximum + 1])
        ]
        boundary = (
            boundaries[-1] if boundaries else remaining.rfind(" ", 0, maximum + 1)
        )
        if boundary <= 0:
            boundary = maximum
        pieces.append(remaining[:boundary].rstrip())
        remaining = remaining[boundary:].lstrip()
    if remaining:
        pieces.append(remaining)
    return pieces


async def _download(url: str) -> bytes:
    content = bytearray()
    error: Exception | None = None
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=httpx.Timeout(600, connect=30)
    ) as client:
        for _ in range(5):
            headers = {"Accept-Encoding": "identity"}
            if content:
                headers["Range"] = f"bytes={len(content)}-"
            try:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    if content and response.status_code == 200:
                        content.clear()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                    expected = _expected_bytes(response, len(content))
                    if expected is None or len(content) == expected:
                        return bytes(content)
                    error = RuntimeError(
                        f"received {len(content)} bytes, expected {expected}"
                    )
            except httpx.HTTPError as caught:
                error = caught
    raise RuntimeError(f"could not download {url}: {error}")


def _expected_bytes(response: httpx.Response, received: int) -> int | None:
    content_range = response.headers.get("content-range")
    if content_range and "/" in content_range:
        return int(content_range.rsplit("/", maxsplit=1)[1])
    content_length = response.headers.get("content-length")
    if content_length is None:
        return None
    return received if response.status_code == 206 else int(content_length)


def _build_hash(source: RuleSource, dependencies: Sequence[RuleSource]) -> str:
    payload = {
        "version": RULES_VERSION,
        "redactor": REDACTOR_VERSION,
        "source": source.slug,
        "dependencies": [asdict(item) for item in dependencies],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


async def sync(
    pool: Any,
    store: ObjectStore,
    embedder: Embedder,
    redactor: Redactor,
    *,
    sources: Sequence[RuleSource] = SOURCES,
    download: Download = _download,
) -> dict[str, int]:
    bodies: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for source in sources:
        pdf = await download(source.pdf_url)
        digest = hashlib.sha256(pdf).hexdigest()
        await store.put(f"rules/{source.slug}.pdf", pdf, content_type="application/pdf")
        ocr_dpi = GAZETTE_OCR_DPI if source.gazette else OCR_DPI
        ocr_page_segmentation = (
            GAZETTE_OCR_PAGE_SEGMENTATION if source.gazette else OCR_PAGE_SEGMENTATION
        )
        extracted = await extract_text(
            pdf,
            ocr_dpi=ocr_dpi,
            ocr_page_segmentation=ocr_page_segmentation,
        )
        bodies[source.slug] = extracted.text
        hashes[source.slug] = digest

    by_base: dict[str, list[RuleSource]] = {}
    for source in sources:
        if source.base_slug:
            by_base.setdefault(source.base_slug, []).append(source)
    counts: dict[str, int] = {}
    async with pool.acquire() as connection:  # noqa: SIM117
        async with connection.transaction():
            previous = {
                source.slug: await connection.fetchrow(
                    """
                    SELECT pdf_sha256, source_sha256, build_sha256
                    FROM rule_documents WHERE slug = $1
                    """,
                    source.slug,
                )
                for source in sources
            }
            source_changed = {
                source.slug: previous[source.slug] is None
                or previous[source.slug]["pdf_sha256"] != hashes[source.slug]
                or previous[source.slug]["source_sha256"]
                != _build_hash(source, [source])
                for source in sources
            }
            for source in sources:
                if not source_changed[source.slug]:
                    continue
                await connection.execute(
                    """
                    INSERT INTO rule_documents (slug, title, kind, approved_by, text_date,
                                                pdf_url, pdf_key, pdf_sha256, body,
                                                redacted_body, redactor_version,
                                                source_sha256, build_sha256,
                                                visitor_searchable)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    ON CONFLICT (slug) DO UPDATE SET title = EXCLUDED.title,
                        kind = EXCLUDED.kind, approved_by = EXCLUDED.approved_by,
                        text_date = EXCLUDED.text_date, pdf_url = EXCLUDED.pdf_url,
                        pdf_key = EXCLUDED.pdf_key, pdf_sha256 = EXCLUDED.pdf_sha256,
                        body = EXCLUDED.body,
                        redacted_body = EXCLUDED.redacted_body,
                        redactor_version = EXCLUDED.redactor_version,
                        source_sha256 = EXCLUDED.source_sha256,
                        visitor_searchable = EXCLUDED.visitor_searchable,
                        synced_at = now()
                    """,
                    source.slug,
                    source.title,
                    source.kind,
                    source.approved_by,
                    source.text_date,
                    source.pdf_url,
                    f"rules/{source.slug}.pdf",
                    hashes[source.slug],
                    bodies[source.slug],
                    redactor.redact(bodies[source.slug]),
                    REDACTOR_VERSION,
                    _build_hash(source, [source]),
                    _build_hash(source, [source]),
                    source.visitor_searchable,
                )
            # A document whose text did not change still needs a redacted body
            # at the current version, and a modificatoria has no passages that
            # would rebuild it below.
            for source in sources:
                await connection.execute(
                    """
                    UPDATE rule_documents
                    SET redacted_body = $2, redactor_version = $3
                    WHERE slug = $1 AND redactor_version IS DISTINCT FROM $3
                    """,
                    source.slug,
                    redactor.redact(bodies[source.slug]),
                    REDACTOR_VERSION,
                )
            await connection.execute(
                "INSERT INTO embedding_model (model) VALUES ($1) ON CONFLICT DO NOTHING",
                embedder.model,
            )
            held = await connection.fetchval(
                "SELECT model FROM embedding_model FOR SHARE"
            )
            if held != embedder.model:
                raise ValueError(
                    f"the index holds vectors of {held}, but rules use {embedder.model}"
                )
            for source in sources:
                if source.kind == "modificatoria":
                    continue
                amendments = by_base.get(source.slug, [])
                dependencies = [source, *amendments]
                build_hash = _build_hash(source, dependencies)
                prior = previous[source.slug]
                current = await connection.fetchval(
                    "SELECT count(*) FROM rule_passages WHERE document_slug = $1",
                    source.slug,
                )
                dependency_changed = any(
                    source_changed[dependency.slug] for dependency in dependencies
                )
                if (
                    current
                    and prior
                    and prior["build_sha256"] == build_hash
                    and not dependency_changed
                ):
                    counts[source.slug] = current
                    continue
                parts = (
                    _expand_parts(
                        consolidate(
                            source,
                            bodies[source.slug],
                            [(item, bodies[item.slug]) for item in amendments],
                        )
                    )
                    if amendments
                    else split_document(source, bodies[source.slug])
                )
                await connection.execute(
                    "DELETE FROM rule_passages WHERE document_slug = $1", source.slug
                )
                texts = [redactor.redact(part.text) for part in parts]
                vectors = await embedder.embed_passages(texts)
                await connection.executemany(
                    """
                    INSERT INTO rule_passages (document_slug, ordinal, label, text_source,
                                               text_date, pdf_url, text, embedding)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                    """,
                    [
                        (
                            source.slug,
                            ordinal,
                            part.label,
                            part.origin.approved_by,
                            part.origin.text_date,
                            part.origin.pdf_url,
                            text,
                            vector_literal(vector),
                        )
                        for ordinal, (part, text, vector) in enumerate(
                            zip(parts, texts, vectors, strict=True)
                        )
                    ],
                )
                await connection.execute(
                    "UPDATE rule_documents SET build_sha256 = $2 WHERE slug = $1",
                    source.slug,
                    build_hash,
                )
                counts[source.slug] = len(parts)
            await _mark_precedents(connection, sources)
    return counts


async def _mark_precedents(connection: Any, sources: Sequence[RuleSource]) -> None:
    await connection.execute(
        "UPDATE resolutions SET is_precedent = false WHERE is_precedent"
    )
    for source in sources:
        if source.expediente:
            await connection.execute(
                """
                UPDATE resolutions SET is_precedent = true
                WHERE NOT is_precedent
                  AND lower(regexp_replace(expediente, '^0+', '')) =
                      lower(regexp_replace($1, '^0+', ''))
                """,
                source.expediente,
            )
