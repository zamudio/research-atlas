"""Semantic Scholar discovery/enrichment adapter."""

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from time import monotonic
from typing import cast

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.application.source_identity import identified_source
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.infrastructure.providers._http import Sleep, get_with_retries

SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS = 1.1


class AsyncRequestRateLimiter:
    """Serialize request starts with an async, monotonic minimum interval."""

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
        self._lock = asyncio.Lock()
        self._last_started_at: float | None = None

    async def wait(self) -> None:
        """Wait until the next request may start, then reserve that start time."""

        async with self._lock:
            now = self._clock()
            if self._last_started_at is not None:
                remaining = self._minimum_interval_seconds - (now - self._last_started_at)
                if remaining > 0:
                    await self._sleep(remaining)
                    now = self._clock()
            self._last_started_at = now


class SemanticScholarLiteratureSource:
    """Secondary minimal paper relevance search adapter."""

    base_url = "https://api.semanticscholar.org/graph/v1"
    _fields = "paperId,externalIds,title,authors,year,url,publicationTypes,venue"
    provider_id = "semantic_scholar"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        clock: Callable[[], float] = monotonic,
        sleep: Sleep = asyncio.sleep,
        retry_sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._client = client
        self._rate_limiter = AsyncRequestRateLimiter(
            SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
            clock=clock,
            sleep=sleep,
        )
        self._retry_sleep = retry_sleep

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
            before_request=self._rate_limiter.wait,
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
