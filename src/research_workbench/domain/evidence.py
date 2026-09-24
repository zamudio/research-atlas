"""Transparent qualitative evidence assessment."""

from dataclasses import dataclass
from uuid import UUID

from research_workbench.domain.provenance import RecordProvenance


@dataclass(frozen=True, slots=True)
class FindingRecord:
    """A result reported for one study, before cross-study assessment."""

    finding_id: UUID
    source_study_id: UUID
    question_investigated: str
    outcome_investigated: str
    result_summary: str
    direction: str
    status: str
    linked_measurement_ids: tuple[UUID, ...] = ()
    linked_intervention_ids: tuple[UUID, ...] = ()
    effect_estimate: str | None = None
    uncertainty: str | None = None
    moderator_and_subgroup_notes: tuple[str, ...] = ()
    author_interpretation: str | None = None
    reviewer_notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    record_provenance: RecordProvenance | None = None


@dataclass(frozen=True, slots=True)
class EvidenceDimension:
    """One explicitly reasoned dimension of evidence quality."""

    name: str
    level: str
    rationale: str


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Our assessment of a finding or evidence body, separate from author claims."""

    evidence_id: str
    subject_id: str
    supporting_finding_ids: tuple[UUID, ...]
    direction: str
    summary: str
    dimensions: tuple[EvidenceDimension, ...]
    uncertainty_and_limitations: tuple[str, ...]
    generalizability_notes: tuple[str, ...]
    contradictory_finding_ids: tuple[UUID, ...] = ()
    null_finding_ids: tuple[UUID, ...] = ()
    assessor: str | None = None
    record_provenance: RecordProvenance | None = None
