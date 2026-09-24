"""Read-only Zotero reference-library adapter backed by pyzotero."""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from research_atlas.application.source_identity import identified_source
from research_atlas.domain.studies import ExternalIdentifier, SourceProvenance, SourceRecord
from research_atlas.infrastructure.config import ProviderSettings


class ZoteroClient(Protocol):
    def item(self, item_key: str) -> Mapping[str, object]: ...

    def collection_items(self, collection_id: str) -> Iterable[Mapping[str, object]]: ...


class ZoteroReferenceLibrary:
    """Normalize bibliographic Zotero items and omit notes/attachments."""

    ignored_item_types = frozenset({"attachment", "note"})

    def __init__(self, client: ZoteroClient) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: ProviderSettings) -> "ZoteroReferenceLibrary":
        if not settings.zotero_library_id:
            raise ValueError("RESEARCH_ATLAS_ZOTERO_LIBRARY_ID is required")
        from pyzotero import zotero

        client = zotero.Zotero(
            settings.zotero_library_id,
            settings.zotero_library_type,
            settings.zotero_api_key,
        )
        return cls(cast(ZoteroClient, client))

    def get_source(self, provider_record_id: str) -> SourceRecord | None:
        return self._map_item(self._client.item(provider_record_id))

    def list_collection(self, collection_id: str) -> tuple[SourceRecord, ...]:
        return tuple(
            source
            for item in self._client.collection_items(collection_id)
            if (source := self._map_item(item)) is not None
        )

    @staticmethod
    def _map_item(item: Mapping[str, object]) -> SourceRecord | None:
        data_value = item.get("data", item)
        if not isinstance(data_value, Mapping):
            return None
        data = cast(Mapping[str, object], data_value)
        item_type = str(data.get("itemType") or "unknown")
        if item_type in ZoteroReferenceLibrary.ignored_item_types:
            return None
        key = str(data.get("key") or item.get("key") or "")
        identifiers = [ExternalIdentifier("zotero", key)]
        doi = data.get("DOI")
        if isinstance(doi, str) and doi:
            identifiers.append(ExternalIdentifier("doi", doi))
        extra = str(data.get("extra") or "")
        for pattern, namespace in (
            (r"(?im)^PMID\s*:\s*(\S+)", "pmid"),
            (r"(?im)^arXiv\s*:\s*(\S+)", "arxiv"),
        ):
            match = re.search(pattern, extra)
            if match:
                identifiers.append(ExternalIdentifier(namespace, match.group(1)))
        if str(data.get("archive") or "").casefold() == "arxiv" and data.get("archiveLocation"):
            identifiers.append(ExternalIdentifier("arxiv", str(data["archiveLocation"])))

        authors: list[str] = []
        creators = data.get("creators")
        if isinstance(creators, list):
            for creator in cast(list[object], creators):
                if not isinstance(creator, Mapping):
                    continue
                creator_mapping = cast(Mapping[str, object], creator)
                name = creator_mapping.get("name")
                if not isinstance(name, str) or not name:
                    first = str(creator_mapping.get("firstName") or "").strip()
                    last = str(creator_mapping.get("lastName") or "").strip()
                    name = " ".join(part for part in (first, last) if part)
                if name:
                    authors.append(name)
        date_match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(data.get("date") or ""))
        year = int(date_match.group(1)) if date_match else None
        url = data.get("url")
        return identified_source(
            title=str(data.get("title") or "Untitled source"),
            authors=authors,
            year=year,
            source_type=item_type,
            provenance=(SourceProvenance("zotero", key, datetime.now(UTC)),),
            identifiers=identifiers,
            source_url=url if isinstance(url, str) else None,
        )
