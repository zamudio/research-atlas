"""Provider-neutral contributor identifier normalization and exact resolution."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from research_atlas.domain.contributors import (
    ContributionObservation,
    ContributionResolution,
    Contributor,
    ContributorIdentifier,
)

TRUSTED_EXACT_CONTRIBUTOR_IDENTIFIER_NAMESPACES = frozenset({"orcid"})


@dataclass(frozen=True, order=True, slots=True)
class ExactContributorKey:
    """One typed piece of trusted exact contributor identity evidence."""

    kind: Literal["external_identifier", "provider_record"]
    namespace: str
    value: str


@dataclass(frozen=True, slots=True)
class ExactContributorResolution:
    """Resolved Contributors, their links, and observations lacking exact evidence."""

    contributors: tuple[Contributor, ...]
    resolutions: tuple[ContributionResolution, ...]
    unresolved_contribution_observation_ids: tuple[UUID, ...]


class ContributorIdentityConflictError(ValueError):
    """Raised when an exact component contains contradictory contributor identifiers."""

    def __init__(
        self,
        namespace: str,
        values: Iterable[str],
        *,
        contributor_ids: Iterable[UUID] = (),
    ) -> None:
        self.namespace = namespace
        self.values = tuple(sorted(set(values)))
        self.contributor_ids = tuple(sorted(set(contributor_ids), key=str))
        rendered_values = ", ".join(repr(value) for value in self.values)
        super().__init__(
            f"conflicting exact contributor identity for {namespace}: {rendered_values}"
        )


def _normalize_namespace(namespace: str) -> str:
    return re.sub(r"[\s-]+", "_", namespace.strip().lower())


def normalize_orcid(value: str) -> str | None:
    """Return a canonical, checksum-valid ORCID, or ``None`` when it is invalid."""

    normalized = re.sub(
        r"^https?://(?:www\.)?orcid\.org/", "", value.strip(), flags=re.IGNORECASE
    ).strip("/ ")
    compact = normalized.replace("-", "")
    if not re.fullmatch(r"\d{15}[\dXx]", compact):
        return None

    total = 0
    for character in compact[:15]:
        total = (total + int(character)) * 2
    check_value = (12 - total % 11) % 11
    expected_check = "X" if check_value == 10 else str(check_value)
    if compact[-1].upper() != expected_check:
        return None

    canonical = f"{compact[:4]}-{compact[4:8]}-{compact[8:12]}-{compact[12:]}"
    return canonical.upper()


def normalize_contributor_identifier(identifier: ContributorIdentifier) -> ContributorIdentifier:
    """Normalize contributor metadata while preserving invalid or untrusted evidence."""

    namespace = _normalize_namespace(identifier.namespace)
    value = identifier.value.strip()
    if namespace == "orcid":
        value = normalize_orcid(value) or value
    return ContributorIdentifier(namespace=namespace, value=value)


def normalize_contributor_identifiers(
    identifiers: Iterable[ContributorIdentifier],
) -> tuple[ContributorIdentifier, ...]:
    """Normalize, de-duplicate, and deterministically order contributor identifiers."""

    normalized = {normalize_contributor_identifier(identifier) for identifier in identifiers}
    return tuple(sorted(normalized, key=lambda item: (item.namespace, item.value)))


def exact_contributor_match_keys(
    observation: ContributionObservation,
) -> frozenset[ExactContributorKey]:
    """Return trusted exact external and provider-native identity keys."""

    keys: set[ExactContributorKey] = set()
    for identifier in normalize_contributor_identifiers(observation.external_identifiers):
        if identifier.namespace not in TRUSTED_EXACT_CONTRIBUTOR_IDENTIFIER_NAMESPACES:
            continue
        canonical_orcid = normalize_orcid(identifier.value)
        if canonical_orcid is not None:
            keys.add(
                ExactContributorKey("external_identifier", identifier.namespace, canonical_orcid)
            )

    provider = observation.provider.strip().lower()
    if observation.provider_record_id is not None:
        provider_record_id = observation.provider_record_id.strip()
        if provider and provider_record_id:
            keys.add(ExactContributorKey("provider_record", provider, provider_record_id))
    return frozenset(keys)


def observed_contribution(
    *,
    source_id: UUID,
    display_name: str,
    role: str,
    provider: str,
    provider_record_id: str | None = None,
    provider_position: int | None = None,
    external_identifiers: Iterable[ContributorIdentifier] = (),
    observed_contributor_kind: str | None = None,
    retrieved_at: datetime | None = None,
) -> ContributionObservation:
    """Build a normalized provider observation with a new opaque Atlas UUIDv7."""

    normalized_provider_record_id = (
        provider_record_id.strip() if provider_record_id is not None else None
    )
    normalized_kind = (
        observed_contributor_kind.strip().lower() if observed_contributor_kind is not None else None
    )
    return ContributionObservation(
        contribution_observation_id=uuid7(),
        source_id=source_id,
        display_name=display_name.strip(),
        role=role.strip(),
        provider=provider.strip().lower(),
        provider_record_id=normalized_provider_record_id,
        provider_position=provider_position,
        external_identifiers=normalize_contributor_identifiers(external_identifiers),
        observed_contributor_kind=normalized_kind,
        retrieved_at=retrieved_at,
    )


def _component_kind(observations: Iterable[ContributionObservation]) -> str:
    informative_kinds = {
        normalized_kind
        for observation in observations
        if observation.observed_contributor_kind is not None
        and (normalized_kind := observation.observed_contributor_kind.strip().lower()) != "unknown"
    }
    if len(informative_kinds) == 1:
        return informative_kinds.pop()
    return "unknown"


def _raise_for_identity_conflicts(observations: Iterable[ContributionObservation]) -> None:
    valid_orcids = {
        canonical_orcid
        for observation in observations
        for identifier in observation.external_identifiers
        if _normalize_namespace(identifier.namespace) == "orcid"
        and (canonical_orcid := normalize_orcid(identifier.value)) is not None
    }
    if len(valid_orcids) > 1:
        raise ContributorIdentityConflictError("orcid", valid_orcids)


def resolve_exact_contributors(
    observations: Iterable[ContributionObservation],
    *,
    existing_contributors: Iterable[Contributor] = (),
    existing_resolutions: Iterable[ContributionResolution] = (),
) -> ExactContributorResolution:
    """Resolve trusted exact evidence while preserving established Atlas identity state."""

    candidates = tuple(observations)
    established_contributors = tuple(existing_contributors)
    established_resolutions = tuple(existing_resolutions)

    observation_index_by_id: dict[UUID, int] = {}
    for index, observation in enumerate(candidates):
        if observation.contribution_observation_id in observation_index_by_id:
            raise ValueError(
                "duplicate contribution_observation_id in supplied observations: "
                f"{observation.contribution_observation_id}"
            )
        observation_index_by_id[observation.contribution_observation_id] = index

    existing_contributor_by_id: dict[UUID, Contributor] = {}
    for contributor in established_contributors:
        if contributor.contributor_id in existing_contributor_by_id:
            raise ValueError(
                f"duplicate contributor_id in existing_contributors: {contributor.contributor_id}"
            )
        existing_contributor_by_id[contributor.contributor_id] = contributor

    existing_resolution_by_observation_id: dict[UUID, ContributionResolution] = {}
    for resolution in established_resolutions:
        observation_id = resolution.contribution_observation_id
        if observation_id not in observation_index_by_id:
            raise ValueError(
                "existing resolution refers to an observation not supplied to the resolver: "
                f"{observation_id}"
            )
        if observation_id in existing_resolution_by_observation_id:
            raise ValueError(
                f"multiple existing resolutions for contribution observation: {observation_id}"
            )
        if resolution.contributor_id not in existing_contributor_by_id:
            raise ValueError(
                "existing resolution refers to a contributor absent from existing_contributors: "
                f"{resolution.contributor_id}"
            )
        existing_resolution_by_observation_id[observation_id] = resolution

    parents = list(range(len(candidates)))
    keys_by_index: list[frozenset[ExactContributorKey]] = []

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        survivor, joined = sorted((first_root, second_root))
        parents[joined] = survivor

    first_index_by_key: dict[ExactContributorKey, int] = {}
    for index, observation in enumerate(candidates):
        keys = exact_contributor_match_keys(observation)
        keys_by_index.append(keys)
        for key in keys:
            previous_index = first_index_by_key.setdefault(key, index)
            union(previous_index, index)

    component_indices: dict[int, list[int]] = {}
    for index, keys in enumerate(keys_by_index):
        if keys:
            component_indices.setdefault(find(index), []).append(index)

    new_contributor_by_id: dict[UUID, Contributor] = {}
    contributor_id_by_index = {
        observation_index_by_id[observation_id]: resolution.contributor_id
        for observation_id, resolution in existing_resolution_by_observation_id.items()
    }
    for indices in component_indices.values():
        component = tuple(candidates[index] for index in indices)
        established_ids = {
            contributor_id_by_index[index] for index in indices if index in contributor_id_by_index
        }
        if len(established_ids) > 1:
            raise ContributorIdentityConflictError(
                "contributor_id",
                (str(contributor_id) for contributor_id in established_ids),
                contributor_ids=established_ids,
            )
        _raise_for_identity_conflicts(component)
        if established_ids:
            contributor_id = next(iter(established_ids))
        else:
            contributor = Contributor(
                contributor_id=uuid7(),
                display_name=component[0].display_name,
                kind=_component_kind(component),
            )
            contributor_id = contributor.contributor_id
            new_contributor_by_id[contributor_id] = contributor
        for index in indices:
            contributor_id_by_index[index] = contributor_id

    contributors: list[Contributor] = []
    emitted_contributor_ids: set[UUID] = set()
    for index in range(len(candidates)):
        contributor_id = contributor_id_by_index.get(index)
        if contributor_id is None or contributor_id in emitted_contributor_ids:
            continue
        contributor = (
            existing_contributor_by_id.get(contributor_id) or new_contributor_by_id[contributor_id]
        )
        contributors.append(contributor)
        emitted_contributor_ids.add(contributor_id)

    resolutions: list[ContributionResolution] = []
    for index, observation in enumerate(candidates):
        if index not in contributor_id_by_index:
            continue
        existing_resolution = existing_resolution_by_observation_id.get(
            observation.contribution_observation_id
        )
        if existing_resolution is not None:
            resolutions.append(existing_resolution)
        else:
            resolutions.append(
                ContributionResolution(
                    contribution_observation_id=observation.contribution_observation_id,
                    contributor_id=contributor_id_by_index[index],
                    resolution_basis="exact_identity",
                )
            )
    unresolved_ids = tuple(
        observation.contribution_observation_id
        for index, observation in enumerate(candidates)
        if index not in contributor_id_by_index
    )
    return ExactContributorResolution(
        contributors=tuple(contributors),
        resolutions=tuple(resolutions),
        unresolved_contribution_observation_ids=unresolved_ids,
    )
