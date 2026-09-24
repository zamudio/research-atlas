"""Port for a reference library such as Zotero."""

from collections.abc import Iterable
from typing import Protocol

from research_atlas.domain.studies import SourceRecord


class ReferenceLibrary(Protocol):
    """Provider-neutral access to normalized references."""

    def get_source(self, provider_record_id: str) -> SourceRecord | None: ...

    def list_collection(self, collection_id: str) -> Iterable[SourceRecord]: ...
