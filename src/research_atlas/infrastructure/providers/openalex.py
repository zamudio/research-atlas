"""OpenAlex discovery adapter."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import ClassVar

import httpx
from pydantic import Field

from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureRecord,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance
from research_atlas.infrastructure.providers._http import Sleep, get_with_retries
from research_atlas.infrastructure.providers._response import (
    WireModel,
    malformed,
    next_checkpoint,
    parse_response,
    read_checkpoint,
)


class _Author(WireModel):
    id: str | None = None
    display_name: str | None = None
    orcid: str | None = None


class _Authorship(WireModel):
    raw_author_name: str | None = None
    author: _Author | None = None


class _Location(WireModel):
    landing_page_url: str | None = None


class _Work(WireModel):
    id: str = Field(min_length=1)
    doi: str | None = None
    title: str | None = None
    authorships: list[_Authorship] | None = None
    publication_year: int | None = None
    publication_date: str | None = None
    type: str | None = None
    primary_location: _Location | None = None
    ids: dict[str, str | int | None] | None = None


class _Meta(WireModel):
    next_cursor: str | None


class _Results(WireModel):
    results: list[_Work]


class _Envelope(_Results):
    meta: _Meta


OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS = 1.1
OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS = 2_000


class OpenAlexSemanticRequestCoordinator:
    """Grant semantic request starts with a process-local monotonic minimum interval."""

    def __init__(
        self,
        minimum_interval_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if minimum_interval_seconds <= 0:
            raise ValueError("minimum interval must be positive")
        self._minimum_interval_seconds = minimum_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._start_lock = Lock()
        self._last_start_at: float | None = None

    async def wait(self) -> None:
        """Sleep and re-check until this caller can atomically claim a request start."""

        while True:
            with self._start_lock:
                now = self._clock()
                delay = (
                    0.0
                    if self._last_start_at is None
                    else self._last_start_at + self._minimum_interval_seconds - now
                )
                if delay <= 0:
                    self._last_start_at = now
                    return
            await self._sleep(delay)


_DEFAULT_SEMANTIC_REQUEST_COORDINATOR = OpenAlexSemanticRequestCoordinator(
    OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS
)


class OpenAlexLiteratureSource:
    """Primary discovery adapter using OpenAlex works search."""

    base_url = "https://api.openalex.org"
    _select = ",".join(
        (
            "id",
            "doi",
            "title",
            "authorships",
            "publication_year",
            "publication_date",
            "type",
            "primary_location",
            "ids",
        )
    )
    provider_id = "openalex"
    operation_id = "openalex.search"

    def __init__(self, api_key: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def search(
        self, query: LiteratureQuery, *, checkpoint: str | None = None
    ) -> LiteratureBatch:
        if self._client is not None:
            return await self._search(self._client, query, checkpoint)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await self._search(client, query, checkpoint)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery, checkpoint: str | None
    ) -> LiteratureBatch:
        cursor, offset = read_checkpoint(checkpoint, self.operation_id, query)
        params: dict[str, str | int] = {
            "search": query.query,
            "per_page": query.limit,
            "cursor": cursor,
            "select": self._select,
        }
        reserved = {
            "search",
            "search.exact",
            "search.semantic",
            "per_page",
            "cursor",
            "select",
            "page",
            "api_key",
        }
        if {parameter.name for parameter in query.parameters} & reserved:
            raise ValueError("OpenAlex adapter manages reserved parameters")
        request_params = httpx.QueryParams(params)
        for parameter in query.parameters:
            request_params = request_params.add(parameter.name, parameter.value)
        response = await get_with_retries(
            client,
            f"{self.base_url}/works",
            params=request_params,
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else None,
        )
        payload = parse_response(response, _Envelope)
        if len(payload.results) > query.limit:
            raise malformed()
        cursor_after = payload.meta.next_cursor
        if cursor_after is not None and (not cursor_after.strip()):
            raise malformed()
        records = tuple(self._map_work(work) for work in payload.results)
        exhausted = not records or cursor_after is None
        token = (
            None
            if exhausted
            else next_checkpoint(
                cursor_after or "", offset + len(records), self.operation_id, query
            )
        )
        return LiteratureBatch(records, token, exhausted, offset)

    @staticmethod
    def _map_work(work: _Work) -> LiteratureRecord:
        work_id = work.id.strip().rstrip("/").rsplit("/", maxsplit=1)[-1]
        if not work_id:
            raise malformed()
        identifiers = [ExternalIdentifier("openalex", work_id)]
        if work.doi:
            identifiers.append(ExternalIdentifier("doi", work.doi))
        identifiers.extend(
            ExternalIdentifier(namespace, str(value))
            for namespace, value in (work.ids or {}).items()
            if value is not None
        )
        credits: list[BibliographicCredit] = []
        for authorship in work.authorships or ():
            author = authorship.author
            display_name = (authorship.raw_author_name or "").strip() or (
                (author.display_name or "").strip() if author else ""
            )
            author_id = (
                (author.id or "").strip().rstrip("/").rsplit("/", maxsplit=1)[-1] if author else ""
            )
            orcid = (author.orcid or "").strip() if author else ""
            credits.append(
                BibliographicCredit(
                    display_name=display_name,
                    provider_record_id=author_id or None,
                    external_identifiers=(("orcid", orcid),) if orcid else (),
                )
            )
        year = work.publication_year
        if year is None and work.publication_date:
            try:
                year = int(work.publication_date[:4])
            except ValueError:
                pass
        source = identified_source(
            title=work.title or "",
            authors=(credit.display_name for credit in credits),
            year=year,
            source_type=work.type or "unknown",
            provenance=(SourceProvenance("openalex", work_id, datetime.now(UTC)),),
            identifiers=identifiers,
            source_url=work.primary_location.landing_page_url if work.primary_location else None,
        )
        return LiteratureRecord(source, tuple(credits))


class OpenAlexSemanticSearch(OpenAlexLiteratureSource):
    """OpenAlex semantic discovery using one provider-ranked result set."""

    operation_id = "openalex.semantic"
    _maximum_results = 50
    _reserved_parameters: ClassVar[frozenset[str]] = frozenset(
        {
            "cursor",
            "per_page",
            "search",
            "search.exact",
            "search.semantic",
            "select",
        }
    )

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        request_coordinator: OpenAlexSemanticRequestCoordinator | None = None,
        retry_sleep: Sleep = asyncio.sleep,
    ) -> None:
        super().__init__(api_key, client)
        self._request_coordinator = request_coordinator or _DEFAULT_SEMANTIC_REQUEST_COORDINATOR
        self._retry_sleep = retry_sleep

    async def search(
        self, query: LiteratureQuery, *, checkpoint: str | None = None
    ) -> LiteratureBatch:
        if checkpoint is not None:
            raise LiteratureSourceError(
                "semantic search has no continuation", error_type="invalid_checkpoint"
            )
        if query.limit > self._maximum_results:
            raise ValueError(
                f"OpenAlex semantic search supports at most {self._maximum_results} results"
            )
        if len(query.query) > OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS:
            raise ValueError("OpenAlex semantic search input must be at most 2,000 characters")
        return await super().search(query)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery, checkpoint: str | None
    ) -> LiteratureBatch:
        reserved = {parameter.name for parameter in query.parameters} & (
            self._reserved_parameters | {"page", "api_key"}
        )
        if reserved:
            raise ValueError("OpenAlex semantic adapter manages reserved parameters")
        params = httpx.QueryParams(
            {"search.semantic": query.query, "per_page": query.limit, "select": self._select}
        )
        for parameter in query.parameters:
            params = params.add(parameter.name, parameter.value)
        response = await get_with_retries(
            client,
            f"{self.base_url}/works",
            params=params,
            headers={"Authorization": f"Bearer {self._api_key}"} if self._api_key else None,
            sleep=self._retry_sleep,
            before_request=self._request_coordinator.wait,
        )
        payload = parse_response(response, _Results)
        if len(payload.results) > query.limit:
            raise malformed()
        records = tuple(self._map_work(work) for work in payload.results)
        return LiteratureBatch(records, None, True)
