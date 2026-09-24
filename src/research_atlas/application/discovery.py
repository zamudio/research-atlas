"""Provider-neutral literature discovery use case."""

import asyncio
from collections.abc import Sequence
from typing import TypedDict

from research_atlas.application.ports.literature_source import LiteratureQuery, LiteratureSource
from research_atlas.application.source_identity import canonical_identity, merge_sources
from research_atlas.domain.studies import SourceRecord


class DiscoveryResult(TypedDict):
    source_id: str
    title: str
    authors: list[str]
    year: int | None
    source_type: str
    source_url: str | None
    external_identifiers: dict[str, list[str]]
    provider_provenance: list[dict[str, str | None]]
    merged_across_providers: bool


class DiscoverSources:
    """Search providers concurrently, then normalize their exact stable identities."""

    def __init__(self, providers: Sequence[LiteratureSource]) -> None:
        if not providers:
            raise ValueError("at least one literature provider is required")
        self._providers = tuple(providers)

    async def execute(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]:
        results = await asyncio.gather(*(provider.search(query) for provider in self._providers))
        discovered = tuple(record for provider_records in results for record in provider_records)
        merged = merge_sources(discovered)
        by_identity = {
            canonical_identity(record.external_identifiers, record.provider_provenance): record
            for record in merged
        }
        relevance_order = dict.fromkeys(
            canonical_identity(record.external_identifiers, record.provider_provenance)
            for record in discovered
        )
        return tuple(by_identity[identity] for identity in relevance_order)[: query.limit]


def serialize_source(record: SourceRecord) -> DiscoveryResult:
    """Create stable, human-reviewable dry-run output without research-run records."""

    identifiers: dict[str, list[str]] = {}
    for identifier in record.external_identifiers:
        identifiers.setdefault(identifier.namespace, []).append(identifier.value)
    providers = {item.provider for item in record.provider_provenance}
    return {
        "source_id": str(record.source_id),
        "title": record.title,
        "authors": list(record.authors),
        "year": record.year,
        "source_type": record.source_type,
        "source_url": record.source_url,
        "external_identifiers": identifiers,
        "provider_provenance": [
            {
                "provider": item.provider,
                "provider_record_id": item.provider_record_id,
                "retrieved_at": item.retrieved_at.isoformat() if item.retrieved_at else None,
            }
            for item in record.provider_provenance
        ],
        "merged_across_providers": len(providers) > 1,
    }


def serialize_sources(records: Sequence[SourceRecord]) -> list[DiscoveryResult]:
    return [serialize_source(record) for record in records]
