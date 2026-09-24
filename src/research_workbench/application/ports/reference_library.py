"""Port for a reference library such as Zotero."""

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from research_workbench.domain.studies import StudyRecord


class ReferenceLibrary(Protocol):
    """Provider-neutral access to normalized references."""

    def get_study(self, study_id: UUID) -> StudyRecord | None: ...

    def list_collection(self, collection_id: str) -> Iterable[StudyRecord]: ...
