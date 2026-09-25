"""OpenAlex discovery adapter."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import ClassVar, cast

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.infrastructure.providers._http import Sleep, get_with_retries

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

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        if query.limit < 1:
            return ()
        if self._client is not None:
            return await self._search(self._client, query)
        async with httpx.AsyncClient(timeout=20.0) as client:
            return await self._search(client, query)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery
    ) -> tuple[SourceRecord, ...]:
        params: dict[str, str | int] = {
            "search": query.query,
            "per_page": min(query.limit, 100),
            "cursor": "*",
            "select": self._select,
        }
        if reserved := {parameter.name for parameter in query.parameters} & params.keys():
            raise ValueError(f"OpenAlex adapter manages reserved parameters: {sorted(reserved)}")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        records: list[SourceRecord] = []
        while len(records) < query.limit:
            request_params = httpx.QueryParams(params)
            for parameter in query.parameters:
                request_params = request_params.add(parameter.name, parameter.value)
            response = await get_with_retries(
                client,
                f"{self.base_url}/works",
                params=request_params,
                headers=headers,
            )
            payload = cast(Mapping[str, object], response.json())
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise ValueError("OpenAlex response results must be a list")
            for raw in cast(list[object], results):
                if isinstance(raw, Mapping):
                    records.append(self._map_work(cast(Mapping[str, object], raw)))
                    if len(records) == query.limit:
                        break
            meta = payload.get("meta", {})
            meta_mapping: Mapping[str, object] = (
                cast(Mapping[str, object], meta) if isinstance(meta, Mapping) else {}
            )
            next_cursor = meta_mapping.get("next_cursor")
            if len(records) >= query.limit or not isinstance(next_cursor, str) or not results:
                break
            params["cursor"] = next_cursor
            params["per_page"] = min(query.limit - len(records), 100)
        return tuple(records)

    @staticmethod
    def _map_work(work: Mapping[str, object]) -> SourceRecord:
        work_id = str(work.get("id") or "").rsplit("/", maxsplit=1)[-1]
        identifiers = [ExternalIdentifier("openalex", work_id)]
        doi = work.get("doi")
        if isinstance(doi, str) and doi:
            identifiers.append(ExternalIdentifier("doi", doi))
        ids = work.get("ids")
        if isinstance(ids, Mapping):
            id_mapping = cast(Mapping[str, object], ids)
            for provider_key, namespace in (
                ("pmid", "pmid"),
                ("pmcid", "pmcid"),
                ("mag", "mag"),
            ):
                value = id_mapping.get(provider_key)
                if isinstance(value, (str, int)) and str(value):
                    identifiers.append(ExternalIdentifier(namespace, str(value)))

        authors: list[str] = []
        authorships = work.get("authorships")
        if isinstance(authorships, list):
            for authorship in cast(list[object], authorships):
                if isinstance(authorship, Mapping):
                    authorship_mapping = cast(Mapping[str, object], authorship)
                    author = authorship_mapping.get("author")
                    author_mapping: Mapping[str, object] = (
                        cast(Mapping[str, object], author) if isinstance(author, Mapping) else {}
                    )
                    name = author_mapping.get("display_name")
                    if isinstance(name, str) and name:
                        authors.append(name)

        location = work.get("primary_location")
        location_mapping: Mapping[str, object] = (
            cast(Mapping[str, object], location) if isinstance(location, Mapping) else {}
        )
        landing_url = location_mapping.get("landing_page_url")
        raw_year = work.get("publication_year")
        year = raw_year if isinstance(raw_year, int) else None
        publication_date = work.get("publication_date")
        if year is None and isinstance(publication_date, str) and len(publication_date) >= 4:
            try:
                year = int(publication_date[:4])
            except ValueError:
                pass
        return identified_source(
            title=str(work.get("title") or "Untitled source"),
            authors=authors,
            year=year,
            source_type=str(work.get("type") or "unknown"),
            provenance=(SourceProvenance("openalex", work_id, datetime.now(UTC)),),
            identifiers=identifiers,
            source_url=landing_url if isinstance(landing_url, str) else None,
        )


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

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        if query.limit > self._maximum_results:
            raise ValueError(
                f"OpenAlex semantic search supports at most {self._maximum_results} results"
            )
        if len(query.query) > OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS:
            raise ValueError(
                "OpenAlex semantic search input must be at most "
                f"{OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS:,} characters"
            )
        return await super().search(query)

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery
    ) -> tuple[SourceRecord, ...]:
        reserved = {parameter.name for parameter in query.parameters} & self._reserved_parameters
        if reserved:
            raise ValueError(
                f"OpenAlex semantic adapter manages reserved parameters: {sorted(reserved)}"
            )
        request_params = httpx.QueryParams(
            {
                "search.semantic": query.query,
                "per_page": query.limit,
                "select": self._select,
            }
        )
        for parameter in query.parameters:
            request_params = request_params.add(parameter.name, parameter.value)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        response = await get_with_retries(
            client,
            f"{self.base_url}/works",
            params=request_params,
            headers=headers,
            sleep=self._retry_sleep,
            before_request=self._request_coordinator.wait,
        )
        payload = cast(Mapping[str, object], response.json())
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("OpenAlex response results must be a list")
        return tuple(
            self._map_work(cast(Mapping[str, object], raw))
            for raw in cast(list[object], results)[: query.limit]
            if isinstance(raw, Mapping)
        )
