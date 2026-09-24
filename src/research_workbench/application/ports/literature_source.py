"""Port for discovering and retrieving literature from external providers."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from research_workbench.domain.studies import StudyRecord


@dataclass(frozen=True, slots=True)
class LiteratureQuery:
    query: str
    filters: tuple[str, ...] = ()


class LiteratureSource(Protocol):
    """External discovery interface; implementations belong outside the domain."""

    def search(self, query: LiteratureQuery) -> Iterable[StudyRecord]: ...
