"""Provider-neutral literature discovery use case."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TypedDict
from uuid import UUID

from research_atlas.application.ports.literature_source import (
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import resolve_exact_sources
from research_atlas.domain.contributors import ContributionObservation
from research_atlas.domain.execution import SearchParameter
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


class SerializedSearchParameter(TypedDict):
    name: str
    value: str


class SerializedSearchSummary(TypedDict):
    provider: str
    operation: str
    query: str
    limit: int
    parameters: list[SerializedSearchParameter]


class SerializedContributorIdentifier(TypedDict):
    namespace: str
    value: str


class SerializedContributionObservation(TypedDict):
    contribution_observation_id: str
    source_id: str
    display_name: str
    role: str
    provider: str
    provider_record_id: str | None
    provider_position: int | None
    external_identifiers: list[SerializedContributorIdentifier]
    observed_contributor_kind: str | None
    retrieved_at: str | None


class SerializedDiscoveryReport(TypedDict):
    searches: list[SerializedSearchSummary]
    provider_outcomes: list[SerializedProviderOutcome]
    normalized_source_count: int
    cross_provider_merge_count: int
    sources: list[SerializedSource]
    contribution_observations: list[SerializedContributionObservation]


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
    parameters: tuple[SearchParameter, ...]


@dataclass(frozen=True, slots=True)
class DiscoveryMembership:
    """Temporary link from one requested search result to its merged source."""

    search_index: int
    source_id: UUID
    result_position: int
    provider_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Normalized sources, search memberships, and outcomes from every provider."""

    searches: tuple[SearchSummary, ...]
    sources: tuple[SourceRecord, ...]
    provider_outcomes: tuple[ProviderOutcome, ...]
    memberships: tuple[DiscoveryMembership, ...] = ()
    contribution_observations: tuple[ContributionObservation, ...] = ()


class DiscoveryFailedError(RuntimeError):
    """Raised when no configured provider completed successfully."""

    def __init__(self, report: DiscoveryReport) -> None:
        self.report = report
        operations = ", ".join(outcome.operation for outcome in report.provider_outcomes)
        super().__init__(f"all literature searches failed: {operations}")


@dataclass(frozen=True, slots=True)
class _ProviderSearchResult:
    outcome: ProviderOutcome
    records: tuple[LiteratureRecord, ...]


class DiscoverSources:
    """Search providers independently, then resolve their exact identity evidence."""

    def __init__(self, searches: Sequence[LiteratureSearchRequest]) -> None:
        if not searches:
            raise ValueError("at least one literature search is required")
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
                parameters=search.query.parameters,
            )
            for search in self._searches
        )
        outcomes = tuple(result.outcome for result in results)
        discovered = tuple(record for result in results for record in result.records)
        if not any(outcome.success for outcome in outcomes):
            raise DiscoveryFailedError(
                DiscoveryReport(
                    searches=summaries,
                    sources=(),
                    provider_outcomes=outcomes,
                )
            )
        resolution = resolve_exact_sources(record.source for record in discovered)
        contribution_observations = tuple(
            replace(observation, source_id=resolution.source_ids_by_input[input_index])
            for input_index, record in enumerate(discovered)
            for observation in record.contribution_observations
        )
        memberships: list[DiscoveryMembership] = []
        input_index = 0
        for search_index, (search, result) in enumerate(zip(self._searches, results, strict=True)):
            seen_source_ids: set[UUID] = set()
            for result_position, literature_record in enumerate(result.records, start=1):
                source_id = resolution.source_ids_by_input[input_index]
                input_index += 1
                if source_id in seen_source_ids:
                    continue
                seen_source_ids.add(source_id)
                memberships.append(
                    DiscoveryMembership(
                        search_index=search_index,
                        source_id=source_id,
                        result_position=result_position,
                        provider_record_id=_provider_record_id(
                            literature_record.source, search.source.provider_id
                        ),
                    )
                )
        return DiscoveryReport(
            searches=summaries,
            sources=resolution.sources,
            provider_outcomes=outcomes,
            memberships=tuple(memberships),
            contribution_observations=contribution_observations,
        )

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


def _provider_record_id(record: SourceRecord, provider: str) -> str | None:
    """Return the unambiguous provider-local ID from this original search result."""

    normalized_provider = provider.strip().casefold()
    record_ids = {
        item.provider_record_id.strip()
        for item in record.provider_provenance
        if item.provider.strip().casefold() == normalized_provider
        and item.provider_record_id
        and item.provider_record_id.strip()
    }
    if len(record_ids) != 1:
        return None
    return next(iter(record_ids))


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


def serialize_contribution_observation(
    observation: ContributionObservation,
) -> SerializedContributionObservation:
    """Create deterministic, JSON-friendly contribution evidence for dry-run review."""

    identifiers = sorted(
        observation.external_identifiers,
        key=lambda identifier: (identifier.namespace, identifier.value),
    )
    return {
        "contribution_observation_id": str(observation.contribution_observation_id),
        "source_id": str(observation.source_id),
        "display_name": observation.display_name,
        "role": observation.role,
        "provider": observation.provider,
        "provider_record_id": observation.provider_record_id,
        "provider_position": observation.provider_position,
        "external_identifiers": [
            {"namespace": identifier.namespace, "value": identifier.value}
            for identifier in identifiers
        ],
        "observed_contributor_kind": observation.observed_contributor_kind,
        "retrieved_at": observation.retrieved_at.isoformat() if observation.retrieved_at else None,
    }


def serialize_report(report: DiscoveryReport) -> SerializedDiscoveryReport:
    """Serialize provider health and normalized sources for a dry-run review."""

    return {
        "searches": [
            {
                "provider": search.provider,
                "operation": search.operation,
                "query": search.query,
                "limit": search.limit,
                "parameters": [
                    {"name": parameter.name, "value": parameter.value}
                    for parameter in search.parameters
                ],
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
        "contribution_observations": [
            serialize_contribution_observation(observation)
            for observation in report.contribution_observations
        ],
    }
