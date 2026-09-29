"""Embedded bibliographic credit supplied by a publication metadata provider."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BibliographicCredit:
    """An ordered credit within one provider record, without Atlas contributor identity.

    The enclosing LiteratureRecord supplies publication and provider provenance.
    External identifiers are preserved as supplied (namespace, value) pairs, not
    used to resolve people or organizations. Tuple order preserves the byline.
    """

    display_name: str
    role: str = "author"
    provider_record_id: str | None = None
    external_identifiers: tuple[tuple[str, str], ...] = ()
    kind: str | None = None
