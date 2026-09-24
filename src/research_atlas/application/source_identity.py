"""Provider-independent scholarly source identity and deterministic merging."""

import re
from collections.abc import Iterable
from dataclasses import replace
from uuid import UUID, uuid5

from research_atlas.domain.studies import (
    ExternalIdentifier,
    SourceProvenance,
    SourceRecord,
)

SOURCE_ID_NAMESPACE = UUID("891ff11c-2e1c-5a41-8e1a-928fa5359936")

_NAMESPACE_ALIASES = {
    "pubmed": "pmid",
    "pubmedid": "pmid",
    "arxiv_id": "arxiv",
    "openalex_id": "openalex",
    "semantic_scholar": "semanticscholar",
    "paperid": "semanticscholar",
}
_IDENTITY_PRIORITY = ("doi", "pmid", "arxiv")


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


def canonical_identity(
    identifiers: Iterable[ExternalIdentifier],
    provenance: Iterable[SourceProvenance] = (),
) -> str:
    """Choose a stable identity, preferring registry IDs over provider-local IDs."""

    normalized = normalize_identifiers(identifiers)
    for namespace in _IDENTITY_PRIORITY:
        values = sorted(item.value for item in normalized if item.namespace == namespace)
        if values:
            return f"{namespace}:{values[0]}"

    provider_ids = sorted(
        (item.provider.strip().lower(), item.provider_record_id.strip())
        for item in provenance
        if item.provider.strip() and item.provider_record_id and item.provider_record_id.strip()
    )
    if not provider_ids:
        raise ValueError("a source requires a stable scholarly or provider identifier")
    provider, provider_record_id = provider_ids[0]
    return f"provider:{provider}:{provider_record_id}"


def stable_source_id(
    identifiers: Iterable[ExternalIdentifier],
    provenance: Iterable[SourceProvenance] = (),
) -> UUID:
    """Generate the same UUID5 whenever the canonical identity is the same."""

    return uuid5(SOURCE_ID_NAMESPACE, canonical_identity(identifiers, provenance))


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
    """Build a normalized source whose internal ID derives only from stable identity."""

    normalized_ids = normalize_identifiers(identifiers)
    normalized_provenance = _merge_provenance(provenance)
    return SourceRecord(
        source_id=stable_source_id(normalized_ids, normalized_provenance),
        title=title.strip(),
        authors=tuple(author.strip() for author in authors if author.strip()),
        year=year,
        source_type=source_type.strip().lower() or "unknown",
        provider_provenance=normalized_provenance,
        external_identifiers=normalized_ids,
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


def merge_sources(records: Iterable[SourceRecord]) -> tuple[SourceRecord, ...]:
    """Merge only exact canonical identities; titles never participate in matching."""

    grouped: dict[str, list[SourceRecord]] = {}
    for record in records:
        identity = canonical_identity(record.external_identifiers, record.provider_provenance)
        grouped.setdefault(identity, []).append(record)

    merged: list[SourceRecord] = []
    for identity in sorted(grouped):
        matches = grouped[identity]
        identifiers = normalize_identifiers(
            identifier for record in matches for identifier in record.external_identifiers
        )
        provenance = _merge_provenance(
            item for record in matches for item in record.provider_provenance
        )
        author_lists = [
            tuple(author.strip() for author in record.authors if author.strip())
            for record in matches
            if record.authors
        ]
        base_authors = (
            sorted(
                author_lists,
                key=lambda values: (-len(values), tuple(value.casefold() for value in values)),
            )[0]
            if author_lists
            else ()
        )
        seen_authors = {author.casefold() for author in base_authors}
        additional_authors = sorted(
            {
                author.strip()
                for record in matches
                for author in record.authors
                if author.strip() and author.strip().casefold() not in seen_authors
            },
            key=lambda value: (value.casefold(), value),
        )
        authors = (*base_authors, *additional_authors)
        years = [record.year for record in matches if record.year is not None]
        merged.append(
            SourceRecord(
                source_id=uuid5(SOURCE_ID_NAMESPACE, identity),
                title=_preferred_text((record.title for record in matches), "") or "",
                authors=authors,
                year=min(years) if years else None,
                source_type=_preferred_text((record.source_type for record in matches), "unknown")
                or "unknown",
                provider_provenance=provenance,
                external_identifiers=identifiers,
                source_url=_preferred_text(record.source_url for record in matches),
            )
        )
    return tuple(merged)
