"""Source, study, intervention, and research-run domain records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.versioning import ProtocolReference


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
class ResearchRun:
    """One execution instance of a validated, approved run definition."""

    run_id: str
    project_id: str
    definition_schema_version: str
    definition_fingerprint: str
    definition_reference: str
    status: Literal["running", "completed", "failed", "cancelled"]
    protocol_references: tuple[ProtocolReference, ...]
    taxonomy_reference: str
    taxonomy_version: str
    started_at: datetime
    completed_at: datetime | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.definition_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.definition_fingerprint
        ):
            raise ValueError("definition_fingerprint must be a lowercase SHA-256 hex digest")
        if self.status in {"completed", "failed", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal research runs require completed_at")
        protocol_keys = {
            (reference.protocol_id, reference.phase) for reference in self.protocol_references
        }
        if len(protocol_keys) != len(self.protocol_references):
            raise ValueError("ResearchRun protocol_id and phase pairs must be unique")
