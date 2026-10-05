"""One semantic discovery request; eligibility comes entirely from that response."""

from typing import NotRequired, TypedDict

import httpx
from pydantic import TypeAdapter, ValidationError

from research_atlas.acquire import public_url
from research_atlas.config import Settings
from research_atlas.models import ContentSource, Failure, Work

MAX_CANDIDATES = 50


class _Location(TypedDict, total=False):
    is_oa: bool | None
    pdf_url: str | None


class _Record(TypedDict):
    id: str
    title: NotRequired[str | None]
    doi: NotRequired[str | None]
    publication_year: NotRequired[int | None]
    has_content: NotRequired[dict[str, bool] | None]
    best_oa_location: NotRequired[_Location | None]
    primary_location: NotRequired[_Location | None]
    locations: NotRequired[list[_Location] | None]


_RECORD = TypeAdapter(_Record)
_OBJECT = TypeAdapter(dict[str, object])
_LIST = TypeAdapter(list[object])


def _work(record: _Record) -> Work:
    work = Work(
        openalex_id=record["id"],
        title=record.get("title") or "",
        doi=record.get("doi"),
        year=record.get("publication_year"),
    )
    content = record.get("has_content") or {}
    base = f"https://content.openalex.org/works/{work.openalex_id}"
    routes: list[ContentSource] = []
    if content.get("grobid_xml"):
        routes.append(ContentSource(kind="grobid_xml", url=base + ".grobid-xml"))
    seen: set[str] = set()
    for location in (
        record.get("best_oa_location"),
        record.get("primary_location"),
        *(record.get("locations") or []),
    ):
        if location is None or not location.get("is_oa"):
            continue
        url = location.get("pdf_url")
        if url and url not in seen and public_url(url):
            routes.append(ContentSource(kind="oa_pdf", url=url))
            seen.add(url)
    if content.get("pdf"):
        routes.append(ContentSource(kind="openalex_pdf", url=base + ".pdf"))
    work.routes = tuple(routes)
    return work


async def discover(
    question: str, client: httpx.AsyncClient, settings: Settings
) -> tuple[tuple[Work, ...], tuple[Failure, ...]]:
    response = await client.get(
        "https://api.openalex.org/works",
        params={
            "search.semantic": question,
            "filter": "has_fulltext:true",
            "per_page": MAX_CANDIDATES,
            "select": "id,title,doi,publication_year,has_content,"
            "best_oa_location,primary_location,locations",
        },
        headers={"Authorization": f"Bearer {settings.openalex_api_key.get_secret_value()}"},
        follow_redirects=False,
    )
    response.raise_for_status()
    # A malformed envelope invalidates discovery; a malformed work is a partial failure.
    payload = _OBJECT.validate_json(response.content, strict=True)
    records = _LIST.validate_python(payload.get("results"), strict=True)
    works: list[Work] = []
    failures: list[Failure] = []
    seen: set[str] = set()
    for raw in records[:MAX_CANDIDATES]:
        identity: str | None = None
        try:
            fields = _OBJECT.validate_python(raw, strict=True)
            raw_id = fields.get("id")
            identity = raw_id if isinstance(raw_id, str) else None
            work = _work(_RECORD.validate_python(raw, strict=True))
        except ValidationError, ValueError:
            failures.append(
                Failure(openalex_id=identity, stage="discovery", reason="Malformed work metadata.")
            )
            continue
        if work.routes and work.openalex_id not in seen:
            works.append(work)
            seen.add(work.openalex_id)
    return tuple(works), tuple(failures)
