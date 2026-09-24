"""Transparent qualitative evidence assessment."""

from dataclasses import dataclass
from uuid import UUID


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
    supporting_study_ids: tuple[UUID, ...]
    direction: str
    summary: str
    dimensions: tuple[EvidenceDimension, ...]
    uncertainty_and_limitations: tuple[str, ...]
    generalizability_notes: tuple[str, ...]
    contradictory_study_ids: tuple[UUID, ...] = ()
    null_finding_study_ids: tuple[UUID, ...] = ()
    assessor: str | None = None
