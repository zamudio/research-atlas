"""Short PostgreSQL operations for extraction; no connection survives model I/O."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.studies import StudyRecord
from research_atlas.infrastructure.persistence.evidence import (
    load_extraction_document,
    publish_accepted_extraction,
    record_extraction,
    record_source_document,
)


class PostgresExtractionPersistence:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load_document(
        self, run_id: str, source_id: UUID, document_id: UUID
    ) -> tuple[SourceDocument, bytes]:
        return await load_extraction_document(self._engine, run_id, source_id, document_id)

    async def prepare_document(self, document: SourceDocument, content: bytes) -> UUID:
        return await record_source_document(self._engine, document, content)

    async def record_attempt(
        self, extraction: Extraction, configuration: bytes, raw_output: bytes | None
    ) -> None:
        await record_extraction(self._engine, extraction, configuration, raw_output=raw_output)

    async def publish(
        self,
        extraction: Extraction,
        configuration: bytes,
        raw_output: bytes,
        studies: tuple[StudyRecord, ...],
        findings: tuple[FindingRecord, ...],
    ) -> None:
        await publish_accepted_extraction(
            self._engine,
            extraction,
            configuration,
            studies,
            findings,
            raw_output=raw_output,
            select_for_run=True,
        )
