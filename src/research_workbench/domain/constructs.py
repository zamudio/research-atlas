"""Construct and measurement domain records."""

from dataclasses import dataclass
from uuid import UUID

from research_workbench.domain.provenance import RecordProvenance


@dataclass(frozen=True, slots=True)
class SourcedDefinition:
    """A definition and the studies or sources that support its attribution."""

    text: str
    source_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class CandidateObservable:
    """A proposed observable, not an assertion that an inference is valid."""

    description: str
    measurement_method: str | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConstructRecord:
    """Cross-paper registry entry for a construct under review."""

    construct_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    definitions: tuple[SourcedDefinition, ...]
    timescales: tuple[str, ...]
    candidate_moderators: tuple[str, ...]
    candidate_observables: tuple[CandidateObservable, ...]
    product_observability_status: str
    inference_risks: tuple[str, ...]
    candidate_architecture_destinations: tuple[str, ...]
    review_status: str
    record_provenance: RecordProvenance


@dataclass(frozen=True, slots=True)
class MeasurementRecord:
    """How a study operationalized or measured a target construct."""

    measurement_id: UUID
    source_study_id: UUID
    target_construct_id: str
    name: str
    operationalization: str
    instrument_or_signal: str
    timescale: str | None
    record_provenance: RecordProvenance
    validity_notes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
