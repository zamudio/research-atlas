"""Read-only Zotero reference-library adapter backed by pyzotero."""

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from research_atlas.application.contributor_identity import observed_contribution
from research_atlas.application.ports.literature_source import LiteratureRecord
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
    def from_settings(cls, settings: ProviderSettings) -> ZoteroReferenceLibrary:
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
        record = self.get_literature_record(provider_record_id)
        return record.source if record is not None else None

    def list_collection(self, collection_id: str) -> tuple[SourceRecord, ...]:
        return tuple(record.source for record in self.list_collection_records(collection_id))

    def get_literature_record(self, provider_record_id: str) -> LiteratureRecord | None:
        """Return structured source and creator evidence without changing source APIs."""

        return self._map_item(self._client.item(provider_record_id))

    def list_collection_records(self, collection_id: str) -> tuple[LiteratureRecord, ...]:
        """Return structured records for future provider-neutral integration."""

        return tuple(
            record
            for item in self._client.collection_items(collection_id)
            if (record := self._map_item(item)) is not None
        )

    @staticmethod
    def _map_item(item: Mapping[str, object]) -> LiteratureRecord | None:
        data_value = item.get("data", item)
        if not isinstance(data_value, Mapping):
            return None
        data = cast(Mapping[str, object], data_value)
        item_type = str(data.get("itemType") or "unknown")
        if item_type in ZoteroReferenceLibrary.ignored_item_types:
            return None
        key = str(data.get("key") or item.get("key") or "")
        retrieved_at = datetime.now(UTC)
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
        usable_creators: list[tuple[int, str, str, str]] = []
        creators = data.get("creators")
        if isinstance(creators, list):
            for position, creator in enumerate(cast(list[object], creators), start=1):
                if not isinstance(creator, Mapping):
                    continue
                creator_mapping = cast(Mapping[str, object], creator)
                name = creator_mapping.get("name")
                single_field_name = name.strip() if isinstance(name, str) else ""
                first = str(creator_mapping.get("firstName") or "").strip()
                last = str(creator_mapping.get("lastName") or "").strip()
                display_name = single_field_name or " ".join(part for part in (first, last) if part)
                if display_name:
                    authors.append(display_name)
                    raw_role = creator_mapping.get("creatorType")
                    role = raw_role.strip() if isinstance(raw_role, str) else ""
                    usable_creators.append(
                        (
                            position,
                            display_name,
                            role or "unknown",
                            "person" if first or last else "unknown",
                        )
                    )
        date_match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", str(data.get("date") or ""))
        year = int(date_match.group(1)) if date_match else None
        url = data.get("url")
        source = identified_source(
            title=str(data.get("title") or "Untitled source"),
            authors=authors,
            year=year,
            source_type=item_type,
            provenance=(SourceProvenance("zotero", key, retrieved_at),),
            identifiers=identifiers,
            source_url=url if isinstance(url, str) else None,
        )
        return LiteratureRecord(
            source,
            tuple(
                observed_contribution(
                    source_id=source.source_id,
                    display_name=display_name,
                    role=role,
                    provider="zotero",
                    provider_position=position,
                    observed_contributor_kind=contributor_kind,
                    retrieved_at=retrieved_at,
                )
                for position, display_name, role, contributor_kind in usable_creators
            ),
        )
