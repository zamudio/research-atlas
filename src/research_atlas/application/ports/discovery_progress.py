"""The three durable operations required by one bounded ingestion step."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureSourceError,
)


class CheckpointConflict(ValueError):
    """The durable search no longer expects this page."""


class ReplayMismatch(ValueError):
    """A committed batch was replayed with different validated content."""


@dataclass(frozen=True, slots=True)
class SearchResumeState:
    search_execution_id: str
    provider_id: str
    operation_id: str
    query: LiteratureQuery
    checkpoint: str | None
    status: str
    completed_batches: int
    provider_result_count: int


@dataclass(frozen=True, slots=True)
class BatchCommit:
    observation_ids: tuple[UUID, ...]
    source_ids: tuple[UUID | None, ...]
    next_checkpoint: str | None
    exhausted: bool
    conflicted_positions: tuple[int, ...]


class DiscoveryProgress(Protocol):
    async def load_search_resume_state(self, search_id: str) -> SearchResumeState: ...

    async def commit_discovery_batch(
        self,
        search_id: str,
        checkpoint: str | None,
        batch: LiteratureBatch,
    ) -> BatchCommit: ...

    async def record_search_failure(
        self,
        expected: SearchResumeState,
        error: LiteratureSourceError,
    ) -> None: ...
