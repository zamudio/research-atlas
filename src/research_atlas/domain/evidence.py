"""Transparent qualitative evidence assessment."""

from dataclasses import dataclass
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance


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
    record_provenance: RecordProvenance
    linked_measurement_ids: tuple[UUID, ...] = ()
    linked_intervention_ids: tuple[UUID, ...] = ()
    effect_estimate: str | None = None
    uncertainty: str | None = None
    moderator_and_subgroup_notes: tuple[str, ...] = ()
    author_interpretation: str | None = None
    reviewer_notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceDimension:
    """One explicitly reasoned dimension of evidence quality."""

    name: str
    level: str
    rationale: str


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """Our assessment of a claim or evidence body, separate from author findings."""

    evidence_id: str
    claim: str
    supporting_finding_ids: tuple[UUID, ...]
    direction: str
    summary: str
    dimensions: tuple[EvidenceDimension, ...]
    uncertainty_and_limitations: tuple[str, ...]
    generalizability_notes: tuple[str, ...]
    record_provenance: RecordProvenance
    linked_construct_ids: tuple[str, ...] = ()
    contradictory_finding_ids: tuple[UUID, ...] = ()
    null_finding_ids: tuple[UUID, ...] = ()
    assessor: str | None = None
    supersedes_evidence_id: str | None = None


def current_evidence_assessments(
    assessments: tuple[EvidenceAssessment, ...],
) -> tuple[EvidenceAssessment, ...]:
    """Return assessments not superseded by another append-only assessment."""

    superseded = {
        assessment.supersedes_evidence_id
        for assessment in assessments
        if assessment.supersedes_evidence_id is not None
    }
    return tuple(
        assessment for assessment in assessments if assessment.evidence_id not in superseded
    )
