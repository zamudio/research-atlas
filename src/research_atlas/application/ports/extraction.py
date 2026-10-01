"""Only the structured-output boundary and bounded publication operations."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.studies import StudyRecord


class ExtractionProviderError(Exception):
    """Safe local failure category, without provider bodies or request content."""

    def __init__(self, code: str, *, raw_output: bytes | None = None) -> None:
        super().__init__(code)
        self.raw_output = raw_output


class ExtractionEligibilityChanged(Exception):
    """Run/Source membership or screening no longer permits extraction publication."""


@dataclass(frozen=True, slots=True)
class StructuredExtractionResult:
    raw_output: bytes
    model_name: str
    model_version: str
    tool_name: str
    tool_version: str


class StructuredExtractor(Protocol):
    @property
    def configuration(self) -> Mapping[str, object]: ...

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult: ...


class ExtractionPersistence(Protocol):
    async def load_document(
        self, run_id: str, source_id: UUID, document_id: UUID
    ) -> tuple[SourceDocument, bytes]: ...

    async def prepare_document(self, document: SourceDocument, content: bytes) -> UUID: ...

    async def record_attempt(
        self, extraction: Extraction, configuration: bytes, raw_output: bytes | None
    ) -> None: ...

    async def publish(
        self,
        extraction: Extraction,
        configuration: bytes,
        raw_output: bytes,
        studies: tuple[StudyRecord, ...],
        findings: tuple[FindingRecord, ...],
    ) -> None:
        """Publish or raise ExtractionEligibilityChanged if membership/screening changed.

        Other publication invariant or database failures propagate unchanged.
        """
        ...
