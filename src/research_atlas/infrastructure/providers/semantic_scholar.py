"""Semantic Scholar discovery/enrichment adapter."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import cast

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.infrastructure.providers._http import (
    AttemptObserver,
    Sleep,
    default_retry_delay,
    get_with_retries,
    parse_retry_after_delay,
)

SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS = 1.1


class AsyncRequestCoordinator:
    """Grant actual request starts with a monotonic minimum interval."""

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
        """Sleep and re-check until this caller can atomically claim the current start."""

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


def semantic_scholar_retry_delay(status_code: int, retry_after: str | None, attempt: int) -> float:
    """Back off S2 429s for 5 then 10 seconds unless Retry-After is valid."""

    if status_code != 429:
        return default_retry_delay(status_code, retry_after, attempt)
    parsed_retry_after = parse_retry_after_delay(retry_after)
    if parsed_retry_after is not None:
        return parsed_retry_after
    return 5.0 * (2**attempt)


_DEFAULT_REQUEST_COORDINATOR = AsyncRequestCoordinator(SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS)


class _SemanticScholarLiteratureSource:
    """Shared S2 authentication, mapping, retries, and cumulative request pacing."""

    base_url = "https://api.semanticscholar.org/graph/v1"
    _fields = "paperId,externalIds,title,authors,year,url,publicationTypes,venue"
    provider_id = "semantic_scholar"
    operation_id: str

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        request_coordinator: AsyncRequestCoordinator | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Sleep | None = None,
        retry_sleep: Sleep = asyncio.sleep,
        attempt_observer: AttemptObserver | None = None,
        attempt_clock: Callable[[], float] = monotonic,
    ) -> None:
        self._api_key = api_key
        self._client = client
        if request_coordinator is not None and (clock is not None or sleep is not None):
            raise ValueError("request_coordinator cannot be combined with clock or sleep")
        if request_coordinator is not None:
            self._request_coordinator = request_coordinator
        elif clock is not None or sleep is not None:
            self._request_coordinator = AsyncRequestCoordinator(
                SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
                clock=clock or monotonic,
                sleep=sleep or asyncio.sleep,
            )
        else:
            self._request_coordinator = _DEFAULT_REQUEST_COORDINATOR
        self._retry_sleep = retry_sleep
        self._attempt_observer = attempt_observer
        self._attempt_clock = attempt_clock

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
        raise NotImplementedError

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: Mapping[str, str | int],
    ) -> httpx.Response:
        """Issue one S2 GET with shared authentication, retries, and request pacing."""

        headers = {"x-api-key": self._api_key} if self._api_key else None
        return await get_with_retries(
            client,
            url,
            params=params,
            headers=headers,
            sleep=self._retry_sleep,
            before_request=self._request_coordinator.wait,
            retry_delay_policy=semantic_scholar_retry_delay,
            attempt_observer=self._attempt_observer,
            provider=self.provider_id,
            operation_id=self.operation_id,
            endpoint_path=httpx.URL(url).path,
            clock=self._attempt_clock,
        )

    @staticmethod
    def _map_paper(paper: Mapping[str, object]) -> SourceRecord:
        paper_id = str(paper.get("paperId") or "")
        identifiers = [ExternalIdentifier("semanticscholar", paper_id)]
        external_ids = paper.get("externalIds")
        if isinstance(external_ids, Mapping):
            external_id_mapping = cast(Mapping[str, object], external_ids)
            namespace_map = {
                "DOI": "doi",
                "ArXiv": "arxiv",
                "PubMed": "pmid",
                "PubMedCentral": "pmcid",
                "CorpusId": "semantic_scholar_corpus",
                "MAG": "mag",
                "DBLP": "dblp",
                "ACL": "acl",
            }
            for provider_name, namespace in namespace_map.items():
                value = external_id_mapping.get(provider_name)
                if isinstance(value, (str, int)) and str(value):
                    identifiers.append(ExternalIdentifier(namespace, str(value)))
        authors: list[str] = []
        raw_authors = paper.get("authors")
        if isinstance(raw_authors, list):
            for author in cast(list[object], raw_authors):
                author_mapping: Mapping[str, object] = (
                    cast(Mapping[str, object], author) if isinstance(author, Mapping) else {}
                )
                name = author_mapping.get("name")
                if isinstance(name, str) and name:
                    authors.append(name)
        publication_types = paper.get("publicationTypes")
        if isinstance(publication_types, list) and publication_types:
            source_type = str(cast(list[object], publication_types)[0])
        elif paper.get("venue"):
            source_type = "journal-article"
        else:
            source_type = "unknown"
        raw_year = paper.get("year")
        year = raw_year if isinstance(raw_year, int) else None
        url = paper.get("url")
        return identified_source(
            title=str(paper.get("title") or "Untitled source"),
            authors=authors,
            year=year,
            source_type=source_type,
            provenance=(SourceProvenance("semantic_scholar", paper_id, datetime.now(UTC)),),
            identifiers=identifiers,
            source_url=url if isinstance(url, str) else None,
        )


class SemanticScholarRelevanceSearch(_SemanticScholarLiteratureSource):
    """Plain-text, relevance-ranked Semantic Scholar paper discovery."""

    operation_id = "semantic_scholar.relevance"

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery
    ) -> tuple[SourceRecord, ...]:
        response = await self._get(
            client,
            f"{self.base_url}/paper/search",
            params={"query": query.query, "limit": min(query.limit, 100), "fields": self._fields},
        )
        payload = cast(Mapping[str, object], response.json())
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise ValueError("Semantic Scholar response data must be a list")
        return tuple(
            self._map_paper(cast(Mapping[str, object], paper))
            for paper in cast(list[object], data)[: query.limit]
            if isinstance(paper, Mapping)
        )


class SemanticScholarBulkSearch(_SemanticScholarLiteratureSource):
    """Boolean/filter-oriented Semantic Scholar bulk paper retrieval."""

    operation_id = "semantic_scholar.bulk"

    async def _search(
        self, client: httpx.AsyncClient, query: LiteratureQuery
    ) -> tuple[SourceRecord, ...]:
        params: dict[str, str | int] = {"query": query.query, "fields": self._fields}
        records: list[SourceRecord] = []
        seen_tokens: set[str] = set()
        while len(records) < query.limit:
            response = await self._get(
                client,
                f"{self.base_url}/paper/search/bulk",
                params=params,
            )
            payload = cast(Mapping[str, object], response.json())
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise ValueError("Semantic Scholar response data must be a list")
            for paper in cast(list[object], data):
                if isinstance(paper, Mapping):
                    records.append(self._map_paper(cast(Mapping[str, object], paper)))
                    if len(records) == query.limit:
                        break
            token = payload.get("token")
            if (
                len(records) >= query.limit
                or not data
                or not isinstance(token, str)
                or not token
                or token in seen_tokens
            ):
                break
            seen_tokens.add(token)
            params["token"] = token
        return tuple(records)
