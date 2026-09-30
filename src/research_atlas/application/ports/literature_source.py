"""Provider-neutral boundary for literature metadata discovery."""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID, uuid7

from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.studies import SourceRecord


class LiteratureSourceError(RuntimeError):
    """Provider-neutral failure raised by a literature-source adapter."""

    def __init__(self, message: str, *, error_type: str, status_code: int | None = None) -> None:
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LiteratureQuery:
    """Exact text, per-batch limit (1-100), and immutable operation parameters."""

    query: str
    limit: int = 8
    parameters: tuple[SearchParameter, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip() or not 1 <= self.limit <= 100:
            raise ValueError("query must be nonblank and batch limit must be 1-100")


@dataclass(frozen=True, slots=True)
class LiteratureRecord:
    """One whole provider publication observation and its ordered credits.

    The candidate Source snapshot stays unchanged after reconciliation; its UUID is
    provisional. resolved_source_id is null until reconciliation succeeds.
    The Source's provider provenance identifies the originating publication record;
    credit-level provider IDs, when present, describe provider contributor records.
    """

    source: SourceRecord
    credits: tuple[BibliographicCredit, ...] = ()
    observation_id: UUID = field(default_factory=uuid7)
    resolved_source_id: UUID | None = None

    def __post_init__(self) -> None:
        if len(self.source.provider_provenance) != 1:
            raise ValueError("an observation requires exactly one publication provenance")
        provenance = self.source.provider_provenance[0]
        if not provenance.provider.strip() or provenance.retrieved_at is None:
            raise ValueError("observation provider and retrieval time are required")
        if self.source.authors != tuple(credit.display_name for credit in self.credits):
            raise ValueError("byline must preserve the complete ordered credit list")


@dataclass(frozen=True, slots=True)
class LiteratureBatch:
    """One validated page. Persist records and next_checkpoint atomically.

    A failed call returns no batch: retry its INPUT checkpoint. Null checkpoint
    starts a search; exhausted=True terminates it. start_position is a zero-based
    count before this page, allowing resumed ranks without interpreting tokens.
    """

    records: tuple[LiteratureRecord, ...]
    next_checkpoint: str | None
    exhausted: bool
    start_position: int = 0

    def __post_init__(self) -> None:
        if self.exhausted != (self.next_checkpoint is None):
            raise ValueError("non-exhausted batches require a next checkpoint")
        if self.next_checkpoint == "" or self.start_position < 0:
            raise ValueError("invalid checkpoint or batch position")
        if not self.exhausted and not self.records:
            raise ValueError("empty batches must be exhausted")


class LiteratureSource(Protocol):
    """One external discovery operation; implementations belong outside the domain."""

    @property
    def provider_id(self) -> str: ...

    @property
    def operation_id(self) -> str: ...

    async def search(
        self, query: LiteratureQuery, *, checkpoint: str | None = None
    ) -> LiteratureBatch: ...


@dataclass(frozen=True, slots=True)
class LiteratureSearchRequest:
    """Pair a provider operation with the exact query intended for its semantics."""

    source: LiteratureSource
    query: LiteratureQuery
    checkpoint: str | None = None
    max_batches: int = 1

    def __post_init__(self) -> None:
        if self.max_batches < 1:
            raise ValueError("max_batches must be positive")
