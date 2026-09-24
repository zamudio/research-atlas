"""Semantic Scholar discovery/enrichment adapter."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

import httpx

from research_workbench.application.ports.literature_source import LiteratureQuery
from research_workbench.application.source_identity import identified_source
from research_workbench.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_workbench.infrastructure.providers._http import get_with_retries


class SemanticScholarLiteratureSource:
    """Secondary minimal paper relevance search adapter."""

    base_url = "https://api.semanticscholar.org/graph/v1"
    _fields = "paperId,externalIds,title,authors,year,url,publicationTypes,venue"

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
        headers = {"x-api-key": self._api_key} if self._api_key else None
        response = await get_with_retries(
            client,
            f"{self.base_url}/paper/search",
            params={"query": query.query, "limit": min(query.limit, 100), "fields": self._fields},
            headers=headers,
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
