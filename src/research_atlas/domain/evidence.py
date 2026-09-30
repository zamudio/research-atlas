"""Reported study findings and explicit cross-finding Insight contracts.

No extraction or synthesis service is implemented here. Scientific detail can
later grow at validated extraction boundaries without global ontology identities.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from research_atlas.domain.content import EvidenceAnchor, require_sha256, require_tool_versions
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
    evidence_anchors: tuple[EvidenceAnchor, ...]
    effect_estimate: str | None = None
    uncertainty: str | None = None
    moderator_and_subgroup_notes: tuple[str, ...] = ()
    author_interpretation: str | None = None
    reviewer_notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    details: Mapping[str, object] = field(default_factory=dict[str, object])

    def __post_init__(self) -> None:
        if not self.evidence_anchors:
            raise ValueError("findings require an anchor in their extraction document")


@dataclass(frozen=True, slots=True)
class Insight:
    """One Atlas synthesis claim; evidence relationships are explicit separate records."""

    insight_id: UUID
    run_id: str
    claim: str
    configuration_sha256: str
    record_provenance: RecordProvenance
    qualifications: tuple[str, ...] = ()
    uncertainty_and_limitations: tuple[str, ...] = ()
    generalizability_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_sha256(self.configuration_sha256)
        require_tool_versions(self.record_provenance)
        if not self.claim.strip() or not self.run_id.strip():
            raise ValueError("Insight requires claim and producing run")
        if self.run_id != self.record_provenance.created_in_run_id:
            raise ValueError("Insight provenance must identify the producing run")


@dataclass(frozen=True, slots=True)
class InsightFinding:
    """A deliberate relationship decision, never inferred from statistical direction."""

    insight_id: UUID
    finding_id: UUID
    relationship: Literal["supporting", "contradicting", "contextual"]
    rationale: str

    def __post_init__(self) -> None:
        if self.relationship not in {"supporting", "contradicting", "contextual"}:
            raise ValueError("invalid Insight/Finding relationship")
        if not self.rationale.strip():
            raise ValueError("an explicit relationship rationale is required")
