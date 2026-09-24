"""Research-to-product decision records."""

from dataclasses import dataclass
from uuid import UUID

from research_workbench.domain.provenance import RecordProvenance


@dataclass(frozen=True, slots=True)
class ArchitectureCandidate:
    """A reviewable proposal to use research in a product architecture."""

    candidate_id: str
    subject_id: str
    observable_by_product: str
    proposed_raw_signals: tuple[str, ...]
    inference_risks: tuple[str, ...]
    actionability: str
    proposed_destination: str
    rationale: str
    confidence: str
    status: str
    linked_evidence_ids: tuple[str, ...]
    linked_study_ids: tuple[UUID, ...]
    record_provenance: RecordProvenance | None = None


@dataclass(frozen=True, slots=True)
class ProductImplication:
    """A curated implication that may be exported to a consumer project."""

    implication_id: str
    statement: str
    rationale: str
    destination: str
    status: str
    linked_candidate_ids: tuple[str, ...]
    linked_evidence_ids: tuple[str, ...]
    linked_study_ids: tuple[UUID, ...]
    record_provenance: RecordProvenance | None = None
