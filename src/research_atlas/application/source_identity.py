"""Provider-independent scholarly source identity and exact merging."""

import re
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
# automatic matching. Unknown identifiers remain normalized metadata but are not match authority.
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
    """Merged sources plus the final source ID corresponding to each input record."""

    sources: tuple[SourceRecord, ...]
    source_ids_by_input: tuple[UUID, ...]


class SourceIdentityConflictError(ValueError):
    """Raised when an exact identity component contains contradictory strong identifiers."""

    def __init__(self, namespace: str, values: Iterable[str]) -> None:
        self.namespace = namespace
        self.values = tuple(sorted(set(values)))
        rendered_values = ", ".join(repr(value) for value in self.values)
        super().__init__(f"conflicting exact source identity for {namespace}: {rendered_values}")


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
    return ExternalIdentifier(namespace=normalized_namespace, value=normalized_value)


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
        authors=tuple(author.strip() for author in authors if author.strip()),
        year=year,
        source_type=source_type.strip().lower() or "unknown",
        provider_provenance=_merge_provenance(provenance),
        external_identifiers=normalize_identifiers(identifiers),
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


def _preferred_text(values: Iterable[str | None], fallback: str | None = None) -> str | None:
    present = {value.strip() for value in values if value and value.strip()}
    if not present:
        return fallback
    return sorted(present, key=lambda value: (-len(value), value.casefold(), value))[0]


def _raise_for_identity_conflicts(records: Iterable[SourceRecord]) -> None:
    values_by_namespace: dict[str, set[str]] = {
        namespace: set() for namespace in _CONFLICTING_IDENTIFIER_NAMESPACES
    }
    for record in records:
        for identifier in normalize_identifiers(record.external_identifiers):
            if identifier.namespace in values_by_namespace:
                values_by_namespace[identifier.namespace].add(identifier.value)
    for namespace in sorted(values_by_namespace):
        values = values_by_namespace[namespace]
        if len(values) > 1:
            raise SourceIdentityConflictError(namespace, values)


def _merge_component(records: tuple[SourceRecord, ...]) -> SourceRecord:
    _raise_for_identity_conflicts(records)
    identifiers = normalize_identifiers(
        identifier for record in records for identifier in record.external_identifiers
    )
    provenance = _merge_provenance(
        item for record in records for item in record.provider_provenance
    )
    # Choose a whole observed byline. Unioning names can invent extra authors.
    authors = next((record.authors for record in records if record.authors), ())
    years = [record.year for record in records if record.year is not None]
    return SourceRecord(
        source_id=records[0].source_id,
        title=_preferred_text((record.title for record in records), "") or "",
        authors=authors,
        year=min(years) if years else None,
        source_type=_preferred_text((record.source_type for record in records), "unknown")
        or "unknown",
        provider_provenance=provenance,
        external_identifiers=identifiers,
        source_url=_preferred_text(record.source_url for record in records),
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
    for indices in component_indices.values():
        merged = _merge_component(tuple(candidates[index] for index in indices))
        merged_sources.append(merged)
        for index in indices:
            source_ids_by_input[index] = merged.source_id

    if any(source_id is None for source_id in source_ids_by_input):
        raise RuntimeError("exact source resolution did not map every input record")
    return ExactSourceResolution(
        sources=tuple(merged_sources),
        source_ids_by_input=tuple(
            source_id for source_id in source_ids_by_input if source_id is not None
        ),
    )


def merge_sources(records: Iterable[SourceRecord]) -> tuple[SourceRecord, ...]:
    """Merge only transitively connected exact keys; titles never participate."""

    return resolve_exact_sources(records).sources
