"""Optional evidence-application records."""

from dataclasses import dataclass

from research_atlas.domain.provenance import RecordProvenance


@dataclass(frozen=True, slots=True)
class ApplicationCandidate:
    """A reviewable proposal to apply assessed evidence for a consumer."""

    candidate_id: str
    observability: str
    proposed_raw_signals: tuple[str, ...]
    inference_risks: tuple[str, ...]
    actionability: str
    proposed_destination: str
    rationale: str
    confidence: str
    status: str
    linked_evidence_ids: tuple[str, ...]
    record_provenance: RecordProvenance
    linked_construct_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionImplication:
    """A curated implication for a consumer decision or action."""

    implication_id: str
    statement: str
    rationale: str
    destination: str
    status: str
    linked_candidate_ids: tuple[str, ...]
    linked_evidence_ids: tuple[str, ...]
    record_provenance: RecordProvenance
