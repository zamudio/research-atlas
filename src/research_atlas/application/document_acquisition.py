"""Acquire one persisted run/Source, with provider I/O outside DB transactions."""

from hashlib import sha256
from uuid import UUID, uuid7

from research_atlas.application.ports.document_acquisition import (
    DocumentAcquirer,
    DocumentAcquisitionProgress,
)
from research_atlas.domain.content import SourceDocument


async def acquire_source_document(
    progress: DocumentAcquisitionProgress,
    run_id: str,
    source_id: UUID,
    acquirer: DocumentAcquirer,
) -> UUID:
    identity = await progress.load_acquisition_identity(run_id, source_id, acquirer.provider_id)
    result = await acquirer.acquire(identity)
    document = SourceDocument(
        document_id=uuid7(),
        source_id=source_id,
        content_kind=result.content_kind,
        retrieval_context=result.retrieval_context,
        retrieved_at=result.retrieved_at,
        status=result.status,
        content_sha256=sha256(result.content).hexdigest() if result.content is not None else None,
        source_url=result.source_url,
        media_type=result.media_type,
    )
    return await progress.commit_document_acquisition(
        run_id, document, result.content, expected_identity=identity
    )
