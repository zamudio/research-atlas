"""Provider-neutral literature discovery use case."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from research_atlas.application.ports.literature_source import (
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import canonical_identity, merge_sources
from research_atlas.domain.studies import SourceRecord


class SerializedSource(TypedDict):
    source_id: str
    title: str
    authors: list[str]
    year: int | None
    source_type: str
    source_url: str | None
    external_identifiers: dict[str, list[str]]
    provider_provenance: list[dict[str, str | None]]
    merged_across_providers: bool


class SerializedProviderOutcome(TypedDict):
    provider: str
    operation: str
    success: bool
    raw_result_count: int | None
    error_type: str | None
    status_code: int | None
    error_message: str | None


class SerializedDiscoveryReport(TypedDict):
    searches: list[dict[str, str | int]]
    provider_outcomes: list[SerializedProviderOutcome]
    normalized_source_count: int
    cross_provider_merge_count: int
    sources: list[SerializedSource]


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    """Provider-neutral health and result-count information for one search."""

    provider: str
    operation: str
    success: bool
    raw_result_count: int | None = None
    error_type: str | None = None
    status_code: int | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class SearchSummary:
    """Serializable identity and exact input for one requested provider operation."""

    provider: str
    operation: str
    query: str
    limit: int


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Normalized sources and observable outcomes from every configured provider."""

    searches: tuple[SearchSummary, ...]
    sources: tuple[SourceRecord, ...]
    provider_outcomes: tuple[ProviderOutcome, ...]


class DiscoveryFailedError(RuntimeError):
    """Raised when no configured provider completed successfully."""

    def __init__(self, report: DiscoveryReport) -> None:
        self.report = report
        operations = ", ".join(outcome.operation for outcome in report.provider_outcomes)
        super().__init__(f"all literature searches failed: {operations}")


@dataclass(frozen=True, slots=True)
class _ProviderSearchResult:
    outcome: ProviderOutcome
    records: tuple[SourceRecord, ...]


class DiscoverSources:
    """Search providers independently, then normalize their exact stable identities."""

    def __init__(self, searches: Sequence[LiteratureSearchRequest]) -> None:
        if not searches:
            raise ValueError("at least one literature search is required")
        operation_ids = [search.source.operation_id for search in searches]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("literature search operation IDs must be unique in one discovery call")
        self._searches = tuple(searches)

    async def execute(self) -> DiscoveryReport:
        """Run explicit provider operations and return their exact-identity union."""

        results = await asyncio.gather(
            *(self._search_provider(search) for search in self._searches)
        )
        summaries = tuple(
            SearchSummary(
                provider=search.source.provider_id,
                operation=search.source.operation_id,
                query=search.query.query,
                limit=search.query.limit,
            )
            for search in self._searches
        )
        outcomes = tuple(result.outcome for result in results)
        discovered = tuple(record for result in results for record in result.records)
        if not any(outcome.success for outcome in outcomes):
            raise DiscoveryFailedError(DiscoveryReport(summaries, (), outcomes))
        merged = merge_sources(discovered)
        by_identity = {
            canonical_identity(record.external_identifiers, record.provider_provenance): record
            for record in merged
        }
        relevance_order = dict.fromkeys(
            canonical_identity(record.external_identifiers, record.provider_provenance)
            for record in discovered
        )
        sources = tuple(by_identity[identity] for identity in relevance_order)
        return DiscoveryReport(summaries, sources, outcomes)

    @staticmethod
    async def _search_provider(
        search: LiteratureSearchRequest,
    ) -> _ProviderSearchResult:
        try:
            records = await search.source.search(search.query)
        except Exception as error:
            if isinstance(error, LiteratureSourceError):
                error_type = error.error_type
                status_code = error.status_code
            else:
                error_type = type(error).__name__
                status_code = None
            return _ProviderSearchResult(
                ProviderOutcome(
                    provider=search.source.provider_id,
                    operation=search.source.operation_id,
                    success=False,
                    error_type=error_type,
                    status_code=status_code,
                    error_message=str(error),
                ),
                (),
            )
        return _ProviderSearchResult(
            ProviderOutcome(
                provider=search.source.provider_id,
                operation=search.source.operation_id,
                success=True,
                raw_result_count=len(records),
            ),
            records,
        )


def serialize_source(record: SourceRecord) -> SerializedSource:
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


def serialize_sources(records: Sequence[SourceRecord]) -> list[SerializedSource]:
    return [serialize_source(record) for record in records]


def serialize_report(report: DiscoveryReport) -> SerializedDiscoveryReport:
    """Serialize provider health and normalized sources for a dry-run review."""

    return {
        "searches": [
            {
                "provider": search.provider,
                "operation": search.operation,
                "query": search.query,
                "limit": search.limit,
            }
            for search in report.searches
        ],
        "provider_outcomes": [
            {
                "provider": outcome.provider,
                "operation": outcome.operation,
                "success": outcome.success,
                "raw_result_count": outcome.raw_result_count,
                "error_type": outcome.error_type,
                "status_code": outcome.status_code,
                "error_message": outcome.error_message,
            }
            for outcome in report.provider_outcomes
        ],
        "normalized_source_count": len(report.sources),
        "cross_provider_merge_count": sum(
            len({item.provider for item in source.provider_provenance}) > 1
            for source in report.sources
        ),
        "sources": serialize_sources(report.sources),
    }
