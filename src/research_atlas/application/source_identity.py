"""Provider-independent scholarly source identity and exact merging."""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Literal
from uuid import UUID, uuid7

from research_atlas.domain.studies import (
    ExternalIdentifier,
    SourceProvenance,
    SourceRecord,
)

_NAMESPACE_ALIASES = {
    "pubmed": "pmid",
    "pubmedid": "pmid",
    "pmc": "pmcid",
    "pubmed_central": "pmcid",
    "pubmedcentral": "pmcid",
    "arxiv_id": "arxiv",
    "openalex_id": "openalex",
    "mag_id": "mag",
    "dblp_id": "dblp",
}

# These namespaces are explicitly authorized as unique publication/source identifiers for
# automatic matching. Unknown identifiers stay on observations and are not match authority.
TRUSTED_EXACT_IDENTIFIER_NAMESPACES = frozenset(
    {
        "acl",
        "arxiv",
        "dblp",
        "doi",
        "mag",
        "openalex",
        "pmcid",
        "pmid",
    }
)
_CONFLICTING_IDENTIFIER_NAMESPACES = frozenset({"arxiv", "doi", "pmcid", "pmid"})


@dataclass(frozen=True, order=True, slots=True)
class ExactSourceKey:
    """One typed piece of exact source-matching evidence."""

    kind: Literal["external_identifier", "provider_record"]
    namespace: str
    value: str


@dataclass(frozen=True, slots=True)
class ExactSourceResolution:
    """Resolved sources, nullable input mapping, and quarantined exact components."""

    sources: tuple[SourceRecord, ...]
    source_ids_by_input: tuple[UUID | None, ...]
    conflicts: tuple[SourceIdentityConflict, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceIdentityConflict:
    """One quarantined exact component; indices refer to the ordered input observations."""

    input_indices: tuple[int, ...]
    conflicting_identifiers: tuple[ExternalIdentifier, ...]


def normalize_doi(value: str) -> str:
    """Return a lower-case bare DOI from common DOI representations."""

    normalized = value.strip()
    normalized = re.sub(
        r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)", "", normalized, flags=re.IGNORECASE
    )
    return re.sub(r"\s+", "", normalized).lower()


def normalize_identifier(namespace: str, value: str) -> ExternalIdentifier:
    """Normalize an external identifier without adopting provider response types."""

    normalized_namespace = re.sub(r"[\s-]+", "_", namespace.strip().lower())
    normalized_namespace = _NAMESPACE_ALIASES.get(normalized_namespace, normalized_namespace)
    normalized_value = value.strip()
    if normalized_namespace == "doi":
        normalized_value = normalize_doi(normalized_value)
    elif normalized_namespace == "pmid":
        normalized_value = re.sub(
            r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/", "", normalized_value, flags=re.I
        ).strip("/ ")
    elif normalized_namespace == "pmcid":
        normalized_value = re.sub(
            r"^https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/",
            "",
            normalized_value,
            flags=re.I,
        ).strip("/ ")
        normalized_value = normalized_value.upper()
    elif normalized_namespace == "arxiv":
        normalized_value = re.sub(
            r"^(?:arxiv\s*:\s*|https?://arxiv\.org/(?:abs|pdf)/)",
            "",
            normalized_value,
            flags=re.I,
        )
        normalized_value = re.sub(r"\.pdf$", "", normalized_value, flags=re.I)
        normalized_value = re.sub(r"v\d+$", "", normalized_value, flags=re.I).lower()
    elif normalized_namespace == "openalex":
        normalized_value = re.sub(
            r"^https?://openalex\.org/", "", normalized_value, flags=re.I
        ).rstrip("/")
    return ExternalIdentifier(namespace=normalized_namespace, value=normalized_value)


def openalex_work_id(value: str) -> str | None:
    """Accept only a bare Work ID or its OpenAlex URL, never an arbitrary content URL."""
    normalized = normalize_identifier("openalex", value).value
    return normalized if re.fullmatch(r"W[0-9]+", normalized) else None


def openalex_acquisition_identity(keys: Iterable[ExactSourceKey]) -> str:
    """Resolve durable keys conservatively, preferring provider-record authority."""
    provider_ids: set[str] = set()
    external_ids: set[str] = set()
    for key in keys:
        if key.namespace != "openalex" or (work_id := openalex_work_id(key.value)) is None:
            continue
        (provider_ids if key.kind == "provider_record" else external_ids).add(work_id)
    usable_ids = provider_ids | external_ids
    if not usable_ids:
        raise ValueError("Source has no usable OpenAlex acquisition identity")
    if len(usable_ids) != 1:
        raise ValueError("Source has ambiguous OpenAlex acquisition identities")
    return next(iter(provider_ids or external_ids))


def normalize_identifiers(
    identifiers: Iterable[ExternalIdentifier],
) -> tuple[ExternalIdentifier, ...]:
    """Normalize, remove blanks/duplicates, and sort identifiers."""

    normalized = {
        identifier
        for raw in identifiers
        if (identifier := normalize_identifier(raw.namespace, raw.value)).namespace
        and identifier.value
    }
    return tuple(sorted(normalized, key=lambda item: (item.namespace, item.value)))


def exact_source_match_keys(record: SourceRecord) -> frozenset[ExactSourceKey]:
    """Return explicitly trusted exact identifiers and typed provider-record keys."""

    keys = {
        ExactSourceKey("external_identifier", identifier.namespace, identifier.value)
        for identifier in normalize_identifiers(record.external_identifiers)
        if identifier.namespace in TRUSTED_EXACT_IDENTIFIER_NAMESPACES
    }
    keys.update(
        ExactSourceKey(
            "provider_record",
            item.provider.strip().lower(),
            item.provider_record_id.strip(),
        )
        for item in record.provider_provenance
        if item.provider.strip() and item.provider_record_id and item.provider_record_id.strip()
    )
    return frozenset(keys)


def identified_source(
    *,
    title: str,
    authors: Iterable[str],
    year: int | None,
    source_type: str,
    provenance: Iterable[SourceProvenance],
    identifiers: Iterable[ExternalIdentifier] = (),
    source_url: str | None = None,
) -> SourceRecord:
    """Build a normalized source candidate with a new opaque internal UUIDv7."""

    return SourceRecord(
        source_id=uuid7(),
        title=title.strip(),
        authors=tuple(author.strip() for author in authors),
        year=year,
        source_type=source_type.strip().lower() or "unknown",
        provider_provenance=_merge_provenance(provenance),
        external_identifiers=tuple(identifiers),
        source_url=source_url.strip() if source_url and source_url.strip() else None,
    )


def _merge_provenance(items: Iterable[SourceProvenance]) -> tuple[SourceProvenance, ...]:
    by_key: dict[tuple[str, str], SourceProvenance] = {}
    for item in items:
        key = (item.provider.strip().lower(), (item.provider_record_id or "").strip())
        normalized = replace(item, provider=key[0], provider_record_id=key[1] or None)
        existing = by_key.get(key)
        if existing is None or (
            normalized.retrieved_at is not None
            and (existing.retrieved_at is None or normalized.retrieved_at > existing.retrieved_at)
        ):
            by_key[key] = normalized
    return tuple(by_key[key] for key in sorted(by_key))


def _conflicting_identifiers(records: Iterable[SourceRecord]) -> tuple[ExternalIdentifier, ...]:
    identifiers = normalize_identifiers(
        identifier for record in records for identifier in record.external_identifiers
    )
    counts = Counter(item.namespace for item in identifiers)
    return tuple(
        item
        for item in identifiers
        if item.namespace in _CONFLICTING_IDENTIFIER_NAMESPACES and counts[item.namespace] > 1
    )


def _merge_component(records: tuple[SourceRecord, ...]) -> SourceRecord:
    # First observation in caller order supplies ALL display fields, even missing ones.
    # Only conflict-free trusted identifiers are promoted to the resolved Source.
    return replace(
        records[0],
        provider_provenance=_merge_provenance(
            item for record in records for item in record.provider_provenance
        ),
        external_identifiers=tuple(
            item
            for item in normalize_identifiers(
                identifier for record in records for identifier in record.external_identifiers
            )
            if item.namespace in TRUSTED_EXACT_IDENTIFIER_NAMESPACES
        ),
    )


def resolve_exact_sources(records: Iterable[SourceRecord]) -> ExactSourceResolution:
    """Resolve transitive exact identity components and retain first-seen candidate IDs."""

    candidates = tuple(records)
    parents = list(range(len(candidates)))

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

    first_index_by_key: dict[ExactSourceKey, int] = {}
    for index, record in enumerate(candidates):
        for key in exact_source_match_keys(record):
            previous_index = first_index_by_key.setdefault(key, index)
            union(previous_index, index)

    component_indices: dict[int, list[int]] = {}
    for index in range(len(candidates)):
        component_indices.setdefault(find(index), []).append(index)

    merged_sources: list[SourceRecord] = []
    source_ids_by_input: list[UUID | None] = [None] * len(candidates)
    conflicts: list[SourceIdentityConflict] = []
    for indices in component_indices.values():
        component = tuple(candidates[index] for index in indices)
        if contradictory := _conflicting_identifiers(component):
            conflicts.append(SourceIdentityConflict(tuple(indices), contradictory))
            continue
        merged = _merge_component(component)
        merged_sources.append(merged)
        for index in indices:
            source_ids_by_input[index] = merged.source_id

    return ExactSourceResolution(
        sources=tuple(merged_sources),
        source_ids_by_input=tuple(source_ids_by_input),
        conflicts=tuple(conflicts),
    )
