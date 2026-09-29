"""Provider-neutral boundary for literature metadata discovery."""

from dataclasses import dataclass
from typing import Protocol

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
    """Exact text, limit, and parameters for one explicitly selected operation."""

    query: str
    limit: int = 8
    parameters: tuple[SearchParameter, ...] = ()


@dataclass(frozen=True, slots=True)
class LiteratureRecord:
    """One whole provider publication observation and its ordered credits.

    Source metadata and credits stay together even after Source reconciliation.
    The Source's provider provenance identifies the originating publication record;
    credit-level provider IDs, when present, describe provider contributor records.
    """

    source: SourceRecord
    credits: tuple[BibliographicCredit, ...] = ()


class LiteratureSource(Protocol):
    """One external discovery operation; implementations belong outside the domain."""

    @property
    def provider_id(self) -> str: ...

    @property
    def operation_id(self) -> str: ...

    async def search(self, query: LiteratureQuery) -> tuple[LiteratureRecord, ...]: ...


@dataclass(frozen=True, slots=True)
class LiteratureSearchRequest:
    """Pair a provider operation with the exact query intended for its semantics."""

    source: LiteratureSource
    query: LiteratureQuery
