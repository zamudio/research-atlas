"""Source, study, intervention, and research-run domain records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.versioning import ProtocolVersions


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    """Identifier assigned by an external registry or provider."""

    namespace: str
    value: str


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    """Where a normalized record came from, without adopting the provider's model."""

    provider: str
    provider_record_id: str | None = None
    retrieved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """A publication, report, chapter, or preprint containing research studies."""

    source_id: UUID
    title: str
    authors: tuple[str, ...]
    year: int | None
    source_type: str
    provider_provenance: tuple[SourceProvenance, ...]
    external_identifiers: tuple[ExternalIdentifier, ...] = ()
    source_url: str | None = None


@dataclass(frozen=True, slots=True)
class StudyRecord:
    """One study or clearly separable analysis reported by a source."""

    study_id: UUID
    source_id: UUID
    study_type: str
    population_summary: str
    domain_summary: str
    setting_summary: str
    sample_summary: str
    record_provenance: RecordProvenance
    study_label: str | None = None


@dataclass(frozen=True, slots=True)
class InterventionRecord:
    """A manipulation or treatment studied in a particular context."""

    intervention_id: UUID
    source_study_id: UUID
    description: str
    comparator: str | None
    target_population: str
    context: str
    outcomes_studied: tuple[str, ...]
    record_provenance: RecordProvenance
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """One reproducible search step within a run."""

    source: str
    query: str
    executed_at: datetime | None = None
    filters: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResearchRun:
    """Versioned metadata for one bounded research pass."""

    run_id: str
    project_id: str
    run_type: str
    purpose: str
    research_questions: tuple[str, ...]
    protocol_versions: ProtocolVersions
    taxonomy_version: str
    search_strategy: str
    search_queries: tuple[SearchQuery, ...]
    inclusion_criteria: tuple[str, ...]
    exclusion_criteria: tuple[str, ...]
    started_at: datetime
    completed_at: datetime | None = None
    included_study_ids: tuple[UUID, ...] = ()
    excluded_source_references: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
