"""Actual research execution and simple run-specific screening records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance


@dataclass(frozen=True, slots=True)
class SearchParameter:
    """One reproducibility-relevant provider search parameter."""

    name: str
    value: str


@dataclass(frozen=True, slots=True)
class SearchExecution:
    """One actual logical search, independent of any prior plan."""

    search_execution_id: str
    run_id: str
    provider_id: str
    operation_id: str
    exact_query: str
    parameters: tuple[SearchParameter, ...]
    requested_limit: int | None
    started_at: datetime
    completed_at: datetime | None
    status: Literal["running", "succeeded", "failed", "cancelled"]
    provider_result_count: int | None = None
    error_type: str | None = None
    error_status_code: int | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.search_execution_id,
                self.run_id,
                self.provider_id,
                self.operation_id,
                self.exact_query,
            )
        ):
            raise ValueError("search execution identities and exact_query must be non-empty")
        if self.requested_limit is not None and self.requested_limit <= 0:
            raise ValueError("requested_limit must be positive")
        if self.provider_result_count is not None and self.provider_result_count < 0:
            raise ValueError("provider_result_count cannot be negative")
        if self.status in {"succeeded", "failed", "cancelled"} and self.completed_at is None:
            raise ValueError("terminal search executions require completed_at")
        if self.status == "succeeded" and self.provider_result_count is None:
            raise ValueError("successful search executions require provider_result_count")
        if self.status == "failed" and self.error_type is None:
            raise ValueError("failed search executions require safe error_type metadata")


@dataclass(frozen=True, slots=True)
class SourceDiscovery:
    """Provenance for a source entering a run through a logical search."""

    discovery_id: str
    search_execution_id: str
    run_id: str
    source_id: UUID
    discovered_at: datetime
    provider_record_id: str | None = None
    result_position: int | None = None

    def __post_init__(self) -> None:
        if not self.discovery_id or not self.search_execution_id or not self.run_id:
            raise ValueError("source discovery identities must be non-empty")
        if self.result_position is not None and self.result_position <= 0:
            raise ValueError("result_position must be positive")


@dataclass(frozen=True, slots=True)
class ScreeningDecision:
    """Run-specific source or study eligibility with an explicit reason."""

    decision_id: str
    run_id: str
    source_id: UUID
    decision: Literal["include", "exclude", "uncertain", "defer", "duplicate"]
    record_provenance: RecordProvenance
    reason_codes: tuple[str, ...] = ()
    study_id: UUID | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id or not self.run_id:
            raise ValueError("screening decision identities must be non-empty")
        if any(not reason_code for reason_code in self.reason_codes):
            raise ValueError("screening reason_codes must be non-empty strings")
