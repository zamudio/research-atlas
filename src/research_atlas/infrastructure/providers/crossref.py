"""Experimental Crossref bibliographic discovery adapter."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.application.source_identity import identified_source, normalize_doi
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.infrastructure.providers._http import get_with_retries


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _publication_year(work: Mapping[str, object]) -> int | None:
    # Publication dates only: deposited/created/indexed are not publication dates.
    for field in ("published", "published-print", "published-online", "issued"):
        parts = _mapping(work.get(field)).get("date-parts")
        if isinstance(parts, list) and parts:
            first = cast(list[object], parts)[0]
            if isinstance(first, list) and first:
                year = cast(list[object], first)[0]
                if type(year) is int and year > 0:
                    return year
    return None


class CrossrefWorksSearch:
    """Metadata-only /works lookup using query.bibliographic, not semantic search."""

    base_url = "https://api.crossref.org"
    provider_id = "crossref"
    operation_id = "crossref.works"
    _page_size = 100
    _select = "DOI,title,author,published,published-print,published-online,issued,type,URL"
    _reserved = frozenset(
        {"query.bibliographic", "rows", "cursor", "select", "mailto", "offset", "sample"}
    )

    def __init__(self, mailto: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._mailto = _text(mailto)
        self._client = client

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        if reserved := {parameter.name for parameter in query.parameters} & self._reserved:
            raise ValueError(f"Crossref adapter manages reserved parameters: {sorted(reserved)}")
        if query.limit < 1:
            return ()
        if self._client is not None:
            return await self._search(self._client, query)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await self._search(client, query)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery
    ) -> tuple[SourceRecord, ...]:
        records: list[SourceRecord] = []
        cursor = "*"
        while len(records) < query.limit:
            rows = min(query.limit - len(records), self._page_size)
            params = httpx.QueryParams(
                {
                    "query.bibliographic": query.query,
                    "rows": rows,
                    "cursor": cursor,
                    "select": self._select,
                }
            )
            if self._mailto:
                params = params.add("mailto", self._mailto)
            for parameter in query.parameters:
                params = params.add(parameter.name, parameter.value)
            response = await get_with_retries(
                client,
                f"{self.base_url}/works",
                params=params,
                headers={"User-Agent": "ResearchAtlas/Crossref-feasibility"},
            )
            payload: object = response.json()
            message = _mapping(_mapping(payload).get("message"))
            raw_items = message.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("Crossref response message.items must be a list")
            items = cast(list[object], raw_items)
            for raw in items[: query.limit - len(records)]:
                if not isinstance(raw, Mapping):
                    raise ValueError("Crossref work must be an object")
                records.append(self._map_work(cast(Mapping[str, object], raw)))
            if len(records) >= query.limit or len(items) < rows:
                break
            next_cursor = message.get("next-cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                break
            # Crossref can reuse a cursor token across pages; a repeated token is not EOF.
            cursor = next_cursor
        return tuple(records)

    @staticmethod
    def _map_work(work: Mapping[str, object]) -> SourceRecord:
        doi = normalize_doi(_text(work.get("DOI")))
        if not doi:
            raise ValueError("Crossref work requires a DOI for stable identity")
        raw_titles = work.get("title")
        titles = cast(list[object], raw_titles) if isinstance(raw_titles, list) else []
        title = next((_text(item) for item in titles if _text(item)), "")
        authors: list[str] = []
        raw_authors = work.get("author")
        if isinstance(raw_authors, list):
            for raw in cast(list[object], raw_authors):
                author = _mapping(raw)
                name = _text(author.get("name")) or " ".join(
                    part for field in ("given", "family") if (part := _text(author.get(field)))
                )
                if name:
                    authors.append(name)
        return identified_source(
            title=title,
            authors=authors,
            year=_publication_year(work),
            source_type=_text(work.get("type")) or "unknown",
            provenance=(SourceProvenance("crossref", doi, datetime.now(UTC)),),
            identifiers=(ExternalIdentifier("doi", doi),),
            source_url=_text(work.get("URL")) or None,
        )
