"""One durable page, with all provider I/O outside database transactions."""

from research_atlas.application.ports.discovery_progress import BatchCommit, DiscoveryProgress
from research_atlas.application.ports.literature_source import (
    LiteratureSource,
    LiteratureSourceError,
)


async def ingest_one_batch(
    progress: DiscoveryProgress,
    search_id: str,
    provider: LiteratureSource,
) -> BatchCommit | None:
    state = await progress.load_search_resume_state(search_id)
    if (provider.provider_id, provider.operation_id) != (state.provider_id, state.operation_id):
        raise ValueError("provider operation does not match persisted search")
    if state.status == "succeeded":
        return None
    if state.status == "cancelled":
        raise ValueError("cancelled search cannot resume")
    try:
        batch = await provider.search(state.query, checkpoint=state.checkpoint)
    except LiteratureSourceError as error:
        await progress.record_search_failure(state, error)
        raise
    return await progress.commit_discovery_batch(search_id, state.checkpoint, batch)
