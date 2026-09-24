"""Port for discovering and retrieving literature from external providers."""

from dataclasses import dataclass
from typing import Protocol

from research_atlas.domain.studies import SourceRecord


class LiteratureSourceError(RuntimeError):
    """Provider-neutral failure raised by a literature-source adapter."""

    def __init__(self, message: str, *, error_type: str, status_code: int | None = None) -> None:
        self.error_type = error_type
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LiteratureQuery:
    """Provider search text and the maximum results requested from each provider."""

    query: str
    limit: int = 8
    filters: tuple[str, ...] = ()


class LiteratureSource(Protocol):
    """External discovery interface; implementations belong outside the domain."""

    @property
    def provider_id(self) -> str: ...

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]: ...
