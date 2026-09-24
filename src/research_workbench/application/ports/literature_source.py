"""Port for discovering and retrieving literature from external providers."""

from dataclasses import dataclass
from typing import Protocol

from research_workbench.domain.studies import SourceRecord


@dataclass(frozen=True, slots=True)
class LiteratureQuery:
    query: str
    limit: int = 8
    filters: tuple[str, ...] = ()


class LiteratureSource(Protocol):
    """External discovery interface; implementations belong outside the domain."""

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]: ...
