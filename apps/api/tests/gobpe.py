"""A stand-in for gob.pe that replays recorded responses.

The recordings in fixtures/gobpe are real: the robots.txt, the listing of the
2022 resolutions (eight entries, all published on 2022-12-31), and the page and
PDF of three of them. The other five entries have no recorded page, so the
stand-in answers 404 for them, as it does for anything unrecorded.
"""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from reclamos_api.corpus.sources import OSINERGMIN, OSIPTEL

COLLECTION_URL = OSIPTEL.collection_url

EMPTY_LISTING = (
    '$(".js-official-documents-search-count").html("0 resultados")\n'
    '$(".js-official-documents-search-results").html("")'
)


def card(resolution_id: int, title: str, published: str) -> str:
    """One result card, shaped as the collection listing renders them."""
    return (
        '<div class="p-4 shadow-campaign-card">'
        f'<div class="border-b">{published}</div>'
        f'<a href="/institucion/osiptel/normas-legales/{resolution_id}-x">'
        f"{title}</a></div>"
    )


def listing_js(total: int, cards: str) -> str:
    """The JavaScript the collection form answers: a count and the cards."""
    return (
        "$('.js-official-documents-search-count')"
        f".html({json.dumps(f'{total} resultados')})\n"
        "$('.js-official-documents-search-results')"
        f".html({json.dumps(cards)})"
    )


FIXTURES = Path(__file__).parent / "fixtures" / "gobpe"
RECORDED_IDS = (6134934, 6134935, 6134941)
LISTED_IDS = (
    6134934,
    6134935,
    6134936,
    6134937,
    6134938,
    6134939,
    6134940,
    6134941,
)
PUBLISHED_ON = date(2022, 12, 31)


class RecordedSite:
    """An httpx transport handler. `requests` keeps what it was asked, in order."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.path == "/robots.txt":
            if url.host == "www.gob.pe":
                return httpx.Response(200, text=(FIXTURES / "robots.txt").read_text())
            return httpx.Response(403)
        if url.path == COLLECTION_URL.removeprefix("https://www.gob.pe"):
            return self._listing(parse_qs(url.query.decode()))
        if url.path == OSINERGMIN.collection_url.removeprefix("https://www.gob.pe"):
            return httpx.Response(200, text=EMPTY_LISTING)
        if url.host == "cdn.www.gob.pe":
            return self._recorded(url.path, "pdf", "application/pdf")
        return self._recorded(url.path, "html", "text/html")

    @staticmethod
    def _listing(query: dict[str, list[str]]) -> httpx.Response:
        start = date.fromisoformat(query["filter[start_date]"][0])
        end = date.fromisoformat(query["filter[end_date]"][0])
        if start <= PUBLISHED_ON <= end:
            return httpx.Response(200, text=(FIXTURES / "listing-2022.js").read_text())
        return httpx.Response(200, text=EMPTY_LISTING)

    @staticmethod
    def _recorded(path: str, extension: str, content_type: str) -> httpx.Response:
        match = re.search(r"/(\d+)-[^/]*$", path)
        recording = FIXTURES / f"{match[1]}.{extension}" if match else None
        if recording is None or not recording.exists():
            return httpx.Response(404, text="not recorded")
        return httpx.Response(
            200, content=recording.read_bytes(), headers={"content-type": content_type}
        )
