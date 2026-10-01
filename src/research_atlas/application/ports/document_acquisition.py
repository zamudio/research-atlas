"""Small contracts for one content acquisition and its durable outcome."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from research_atlas.domain.content import SourceDocument


@dataclass(frozen=True, slots=True)
class DocumentAcquisitionResult:
    status: Literal["usable", "unavailable", "failed", "incomplete"]
    content_kind: str
    retrieval_context: str
    retrieved_at: datetime
    source_url: str
    media_type: str
    content: bytes | None = None

    def __post_init__(self) -> None:
        if self.status == "usable":
            if not self.content:
                raise ValueError("usable acquisition requires nonempty content")
        elif self.content is not None:
            raise ValueError("non-usable acquisition must discard partial content")


class DocumentAcquirer(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def acquire(self, provider_record_id: str) -> DocumentAcquisitionResult: ...


class DocumentAcquisitionProgress(Protocol):
    async def load_acquisition_identity(
        self, run_id: str, source_id: UUID, provider_id: str
    ) -> str: ...

    async def commit_document_acquisition(
        self,
        run_id: str,
        document: SourceDocument,
        content: bytes | None,
        *,
        expected_identity: str,
    ) -> UUID: ...
