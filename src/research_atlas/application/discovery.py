"""Provider-neutral literature discovery use case."""

import asyncio
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from typing import Literal
from uuid import UUID

from research_atlas.application.ports.literature_source import (
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.application.source_identity import SourceIdentityConflict, resolve_exact_sources
from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.studies import SourceRecord


@dataclass(frozen=True, slots=True)
class ProviderOutcome:
    """Provider-neutral health and result-count information for one search."""

    provider: str
    operation: str
    status: Literal["succeeded", "partial", "failed"]
    raw_result_count: int = 0
    completed_batches: int = 0
    checkpoint: str | None = None
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
    checkpoint: str | None
    max_batches: int


@dataclass(frozen=True, slots=True)
class DiscoveryMembership:
    """Temporary link from one requested search result to its merged source."""

    search_index: int
    source_id: UUID | None
    observation_id: UUID
    result_position: int
    provider_record_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    """Normalized sources, search memberships, and outcomes from every provider."""

    searches: tuple[SearchSummary, ...]
    sources: tuple[SourceRecord, ...]
    provider_outcomes: tuple[ProviderOutcome, ...]
    memberships: tuple[DiscoveryMembership, ...] = ()
    metadata_observations: tuple[LiteratureRecord, ...] = ()
    identity_conflicts: tuple[SourceIdentityConflict, ...] = ()


class DiscoveryFailedError(RuntimeError):
    """Raised when every operation failed before returning a validated batch."""

    def __init__(self, report: DiscoveryReport) -> None:
        self.report = report
        operations = ", ".join(outcome.operation for outcome in report.provider_outcomes)
        super().__init__(f"all literature searches failed: {operations}")


@dataclass(frozen=True, slots=True)
class _ProviderSearchResult:
    outcome: ProviderOutcome
    records: tuple[LiteratureRecord, ...]
    positions: tuple[int, ...]


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
                checkpoint=search.checkpoint,
                max_batches=search.max_batches,
            )
            for search in self._searches
        )
        outcomes = tuple(result.outcome for result in results)
        discovered = tuple(record for result in results for record in result.records)
        if all(outcome.status == "failed" for outcome in outcomes):
            raise DiscoveryFailedError(
                DiscoveryReport(
                    searches=summaries,
                    sources=(),
                    provider_outcomes=outcomes,
                )
            )
        resolution = resolve_exact_sources(
            replace(record.source, display_observation_id=record.observation_id)
            for record in discovered
        )
        metadata_observations = tuple(
            replace(
                record,
                resolved_source_id=resolution.source_ids_by_input[index],
            )
            for index, record in enumerate(discovered)
        )
        memberships: list[DiscoveryMembership] = []
        input_index = 0
        for search_index, (search, result) in enumerate(zip(self._searches, results, strict=True)):
            seen_source_ids: set[UUID] = set()
            for result_position, literature_record in zip(
                result.positions, result.records, strict=True
            ):
                source_id = resolution.source_ids_by_input[input_index]
                input_index += 1
                if source_id is not None and source_id in seen_source_ids:
                    continue
                if source_id is not None:
                    seen_source_ids.add(source_id)
                memberships.append(
                    DiscoveryMembership(
                        search_index=search_index,
                        source_id=source_id,
                        observation_id=literature_record.observation_id,
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
            metadata_observations=metadata_observations,
            identity_conflicts=resolution.conflicts,
        )

    @staticmethod
    async def _search_provider(
        search: LiteratureSearchRequest,
    ) -> _ProviderSearchResult:
        records: list[LiteratureRecord] = []
        positions: list[int] = []
        checkpoint = search.checkpoint
        completed_batches = 0
        try:
            for _ in range(search.max_batches):
                batch = await search.source.search(search.query, checkpoint=checkpoint)
                if len(batch.records) > search.query.limit:
                    raise LiteratureSourceError(
                        "provider exceeded batch limit", error_type="malformed_response"
                    )
                if completed_batches and batch.start_position != positions[-1]:
                    raise LiteratureSourceError(
                        "provider returned discontinuous batch", error_type="malformed_response"
                    )
                if not batch.exhausted and batch.next_checkpoint == checkpoint:
                    raise LiteratureSourceError(
                        "provider checkpoint did not advance", error_type="malformed_response"
                    )
                records.extend(batch.records)
                positions.extend(
                    range(batch.start_position + 1, batch.start_position + len(batch.records) + 1)
                )
                checkpoint = batch.next_checkpoint
                completed_batches += 1
                if batch.exhausted:
                    break
        except Exception as error:
            return _ProviderSearchResult(
                ProviderOutcome(
                    provider=search.source.provider_id,
                    operation=search.source.operation_id,
                    status="partial" if completed_batches else "failed",
                    raw_result_count=len(records),
                    completed_batches=completed_batches,
                    checkpoint=checkpoint,
                    error_type=error.error_type
                    if isinstance(error, LiteratureSourceError)
                    else type(error).__name__,
                    status_code=error.status_code
                    if isinstance(error, LiteratureSourceError)
                    else None,
                    error_message=str(error)
                    if isinstance(error, LiteratureSourceError)
                    else "provider operation failed",
                ),
                tuple(records),
                tuple(positions),
            )
        return _ProviderSearchResult(
            ProviderOutcome(
                provider=search.source.provider_id,
                operation=search.source.operation_id,
                status="succeeded" if checkpoint is None else "partial",
                raw_result_count=len(records),
                completed_batches=completed_batches,
                checkpoint=checkpoint,
            ),
            tuple(records),
            tuple(positions),
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


def serialize_source(record: SourceRecord) -> dict[str, object]:
    """Create stable, human-reviewable dry-run output without research-run records."""

    identifiers: dict[str, list[str]] = {}
    for identifier in record.external_identifiers:
        identifiers.setdefault(identifier.namespace, []).append(identifier.value)
    providers = {item.provider for item in record.provider_provenance}
    return {
        "source_id": str(record.source_id),
        "display_observation_id": str(record.display_observation_id)
        if record.display_observation_id
        else None,
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


def serialize_report(report: DiscoveryReport) -> dict[str, object]:
    """Serialize metadata and provider health for developer review, without a bundle."""

    return {
        "searches": [asdict(search) for search in report.searches],
        "provider_outcomes": [asdict(outcome) for outcome in report.provider_outcomes],
        "normalized_source_count": len(report.sources),
        "cross_provider_merge_count": sum(
            len({item.provider for item in source.provider_provenance}) > 1
            for source in report.sources
        ),
        "sources": [serialize_source(source) for source in report.sources],
        "memberships": [
            {
                **asdict(item),
                "source_id": str(item.source_id) if item.source_id else None,
                "observation_id": str(item.observation_id),
            }
            for item in report.memberships
        ],
        "identity_conflicts": [
            {
                "observation_ids": [
                    str(report.metadata_observations[i].observation_id)
                    for i in conflict.input_indices
                ],
                "conflicting_identifiers": [
                    asdict(item) for item in conflict.conflicting_identifiers
                ],
            }
            for conflict in report.identity_conflicts
        ],
        "metadata_observations": [
            {
                **serialize_source(record.source),
                "source_id": str(record.resolved_source_id) if record.resolved_source_id else None,
                "observation_id": str(record.observation_id),
                "credits": [asdict(credit) for credit in record.credits],
            }
            for record in report.metadata_observations
        ],
    }
