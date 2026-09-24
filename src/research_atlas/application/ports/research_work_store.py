"""Persistence seam for resumable research work."""

from typing import Protocol

from research_atlas.schemas.research_records import ResearchRecords


class ResearchWorkStore(Protocol):
    """Load and save validated snapshots without exposing storage technology."""

    def load(self, project_id: str) -> ResearchRecords | None: ...

    def save(self, project_id: str, records: ResearchRecords) -> None: ...
