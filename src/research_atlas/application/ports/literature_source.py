"""Port for discovering and retrieving literature from external providers."""

from dataclasses import dataclass
from typing import Protocol, Self

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
    """Exact text and result limit for one explicitly selected search operation."""

    query: str
    limit: int = 8
    parameters: tuple[SearchParameter, ...] = ()


class LiteratureSource(Protocol):
    """One external discovery operation; implementations belong outside the domain."""

    @property
    def provider_id(self) -> str: ...

    @property
    def operation_id(self) -> str: ...

    async def search(self, query: LiteratureQuery) -> tuple[SourceRecord, ...]: ...


class SearchSpecification(Protocol):
    """Fields required to map an execution-ready logical search without schema coupling."""

    execution_ready: bool
    provider_id: str | None
    operation_id: str | None
    exact_query: str | None
    requested_limit: int | None
    parameters: tuple[SearchParameter, ...]


@dataclass(frozen=True, slots=True)
class LiteratureSearchRequest:
    """Pair one provider operation with the exact query text intended for its semantics."""

    source: LiteratureSource
    query: LiteratureQuery

    @classmethod
    def from_search_spec(cls, source: LiteratureSource, spec: SearchSpecification) -> Self:
        """Preserve one execution-ready SearchSpec as a provider request."""

        if (
            not spec.execution_ready
            or spec.provider_id is None
            or spec.operation_id is None
            or spec.exact_query is None
            or spec.requested_limit is None
        ):
            raise ValueError("a literature search request requires an execution-ready SearchSpec")
        if (source.provider_id, source.operation_id) != (spec.provider_id, spec.operation_id):
            raise ValueError("literature source must match the SearchSpec provider and operation")
        return cls(
            source,
            LiteratureQuery(spec.exact_query, spec.requested_limit, spec.parameters),
        )
