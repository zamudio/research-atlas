"""Provider-neutral contribution observations and contributor identities."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ContributorIdentifier:
    """An externally governed identifier for a bibliographic contributor."""

    namespace: str
    value: str

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.value.strip():
            raise ValueError("contributor identifier namespace and value must be non-blank")


@dataclass(frozen=True, slots=True)
class ContributionObservation:
    """One provider observation of a named contribution to a Source."""

    contribution_observation_id: UUID
    source_id: UUID
    display_name: str
    role: str
    provider: str
    provider_record_id: str | None = None
    provider_position: int | None = None
    external_identifiers: tuple[ContributorIdentifier, ...] = ()
    observed_contributor_kind: str | None = None
    retrieved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("contribution observation display_name must be non-blank")
        if not self.role.strip():
            raise ValueError("contribution observation role must be non-blank")
        if not self.provider.strip():
            raise ValueError("contribution observation provider must be non-blank")
        if self.provider_record_id is not None and not self.provider_record_id.strip():
            raise ValueError("provider_record_id cannot be blank")
        if self.provider_position is not None and self.provider_position <= 0:
            raise ValueError("provider_position must be positive")
        if (
            self.observed_contributor_kind is not None
            and not self.observed_contributor_kind.strip()
        ):
            raise ValueError("observed_contributor_kind cannot be blank")


@dataclass(frozen=True, slots=True)
class Contributor:
    """An Atlas-owned durable identity for a bibliographic contributor."""

    contributor_id: UUID
    display_name: str
    kind: str = "unknown"

    def __post_init__(self) -> None:
        if not self.display_name.strip():
            raise ValueError("contributor display_name must be non-blank")
        if not self.kind.strip():
            raise ValueError("contributor kind must be non-blank")


@dataclass(frozen=True, slots=True)
class ContributionResolution:
    """An explicit resolution from an observation to an Atlas Contributor."""

    contribution_observation_id: UUID
    contributor_id: UUID
    resolution_basis: Literal["exact_identity", "manual_adjudication"]

    def __post_init__(self) -> None:
        if self.resolution_basis not in {"exact_identity", "manual_adjudication"}:
            raise ValueError(f"unsupported contribution resolution basis: {self.resolution_basis}")
