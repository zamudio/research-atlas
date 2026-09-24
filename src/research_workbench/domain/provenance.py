"""Workbench extraction and review provenance."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RecordProvenance:
    """How a normalized or derived record was created and reviewed."""

    created_in_run_id: str
    created_at: datetime
    extraction_method: str
    tool_name: str | None = None
    tool_version: str | None = None
    reviewer: str | None = None
    review_status: str | None = None
    reviewed_at: datetime | None = None
