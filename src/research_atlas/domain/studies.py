"""Source, study, and research-run domain records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance


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
class ResearchRun:
    """A research effort retaining user intent separately from planned operations.

    SearchExecution records own the exact searches that actually ran. These are
    data records only; orchestration and durable progress are later stages.
    """

    run_id: str
    project_id: str
    request: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    created_at: datetime
    research_questions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    plan: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.project_id.strip() or not self.request.strip():
            raise ValueError("run identity, project identity, and request must not be blank")
        if self.status == "running" and self.started_at is None:
            raise ValueError("running research runs require started_at")
        if self.status in {"completed", "failed", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal research runs require completed_at")
