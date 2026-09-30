"""Optional Crossref bibliographic discovery adapter."""

from datetime import UTC, datetime

import httpx
from pydantic import Field

from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureRecord,
)
from research_atlas.application.source_identity import identified_source, normalize_doi
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance
from research_atlas.infrastructure.providers._http import get_with_retries
from research_atlas.infrastructure.providers._response import (
    WireModel,
    malformed,
    next_checkpoint,
    parse_response,
    read_checkpoint,
)


class _Author(WireModel):
    name: str | None = None
    given: str | None = None
    family: str | None = None
    ORCID: str | None = None


class _Date(WireModel):
    date_parts: list[list[int]] = Field(alias="date-parts")


class _Work(WireModel):
    DOI: str = Field(min_length=1)
    title: list[str] | None = None
    author: list[_Author] | None = None
    published: _Date | None = None
    published_print: _Date | None = Field(default=None, alias="published-print")
    published_online: _Date | None = Field(default=None, alias="published-online")
    issued: _Date | None = None
    type: str | None = None
    URL: str | None = None


class _Message(WireModel):
    items: list[_Work]
    next_cursor: str | None = Field(default=None, alias="next-cursor")


class _Envelope(WireModel):
    message: _Message


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _publication_year(work: _Work) -> int | None:
    # Publication dates only: deposited/created/indexed are not publication dates.
    for date in (work.published, work.published_print, work.published_online, work.issued):
        if date and date.date_parts and date.date_parts[0]:
            year = date.date_parts[0][0]
            if year > 0:
                return year
    return None


class CrossrefWorksSearch:
    """Metadata-only /works lookup using query.bibliographic, not semantic search."""

    base_url = "https://api.crossref.org"
    provider_id = "crossref"
    operation_id = "crossref.works"
    _select = "DOI,title,author,published,published-print,published-online,issued,type,URL"
    _cursor_incompatible_sorts = frozenset(
        {"issued", "published", "published-print", "published-online"}
    )
    _reserved = frozenset(
        {"query.bibliographic", "rows", "cursor", "select", "mailto", "offset", "sample"}
    )

    def __init__(self, mailto: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._mailto = _text(mailto)
        self._client = client

    async def search(
        self, query: LiteratureQuery, *, checkpoint: str | None = None
    ) -> LiteratureBatch:
        if {parameter.name for parameter in query.parameters} & self._reserved:
            raise ValueError("Crossref adapter manages reserved parameters")
        if any(
            parameter.name == "sort" and parameter.value in self._cursor_incompatible_sorts
            for parameter in query.parameters
        ):
            raise ValueError("Crossref sort is incompatible with cursor pagination")
        if self._client is not None:
            return await self._search(self._client, query, checkpoint)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await self._search(client, query, checkpoint)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery, checkpoint: str | None
    ) -> LiteratureBatch:
        binding = f"{self.operation_id}:{self._select}:{self._mailto}"
        cursor, offset = read_checkpoint(checkpoint, binding, query)
        params = httpx.QueryParams(
            {
                "query.bibliographic": query.query,
                "rows": query.limit,
                "select": self._select,
                "cursor": cursor,
            }
        )
        if self._mailto:
            params = params.add("mailto", self._mailto)
        filters = [item.value for item in query.parameters if item.name == "filter"]
        if filters:
            params = params.add("filter", ",".join(filters))
        for parameter in query.parameters:
            if parameter.name != "filter":
                params = params.add(parameter.name, parameter.value)
        response = await get_with_retries(
            client,
            f"{self.base_url}/works",
            params=params,
            headers={"User-Agent": "ResearchAtlas"},
        )
        message = parse_response(response, _Envelope).message
        if len(message.items) > query.limit:
            raise malformed()
        exhausted = len(message.items) < query.limit
        cursor_after = message.next_cursor
        if not exhausted and (
            not cursor_after or not cursor_after.strip() or cursor_after == cursor
        ):
            raise malformed()
        records = tuple(self._map_work(work) for work in message.items)
        token = (
            None
            if exhausted
            else next_checkpoint(cursor_after or "", offset + len(records), binding, query)
        )
        return LiteratureBatch(records, token, exhausted, offset)

    @staticmethod
    def _map_work(work: _Work) -> LiteratureRecord:
        doi = normalize_doi(work.DOI)
        if not doi:
            raise malformed()
        title = next((item.strip() for item in work.title or () if item.strip()), "")
        credits: list[BibliographicCredit] = []
        for author in work.author or ():
            name = (author.name or "").strip() or " ".join(
                part.strip() for part in (author.given, author.family) if part and part.strip()
            )
            orcid = (author.ORCID or "").strip()
            credits.append(
                BibliographicCredit(
                    display_name=name,
                    external_identifiers=(("orcid", orcid),) if orcid else (),
                )
            )
        source = identified_source(
            title=title,
            authors=(credit.display_name for credit in credits),
            year=_publication_year(work),
            source_type=work.type or "unknown",
            provenance=(SourceProvenance("crossref", doi, datetime.now(UTC)),),
            identifiers=(ExternalIdentifier("doi", work.DOI),),
            source_url=work.URL,
        )
        return LiteratureRecord(source, tuple(credits))
