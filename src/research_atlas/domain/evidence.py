"""Reported study findings and simple cross-finding assessment data.

No extraction or synthesis service is implemented here. Scientific detail can
later grow at validated extraction boundaries without global ontology identities.
"""

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
    effect_estimate: str | None = None
    uncertainty: str | None = None
    moderator_and_subgroup_notes: tuple[str, ...] = ()
    author_interpretation: str | None = None
    reviewer_notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """A claim-sized assessment referencing findings, not a synthesis engine.

    Retained as simple data until the later Insight stage establishes its actual
    boundary. This trusted record does not validate evidence existence or support.
    """

    evidence_id: str
    claim: str
    record_provenance: RecordProvenance
    supporting_finding_ids: tuple[UUID, ...] = ()
    contradictory_finding_ids: tuple[UUID, ...] = ()
    null_finding_ids: tuple[UUID, ...] = ()
    uncertainty_and_limitations: tuple[str, ...] = ()
    generalizability_notes: tuple[str, ...] = ()
