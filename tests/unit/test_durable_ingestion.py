import asyncio
from dataclasses import replace

import pytest

from research_atlas.application.durable_ingestion import ingest_one_batch
from research_atlas.application.ports.discovery_progress import BatchCommit, SearchResumeState
from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureSourceError,
)


@pytest.mark.parametrize("failure", [False, True])
def test_one_page_reads_progress_before_provider_and_writes_afterward(failure: bool) -> None:
    events: list[str] = []
    state = SearchResumeState(
        "search", "provider", "operation", LiteratureQuery("exact", 3), "opaque", "partial", 1, 3
    )
    expected_batch = LiteratureBatch((), None, True, 3)
    result = BatchCommit((), (), None, True, ())
    expected_error = LiteratureSourceError("private transport detail", error_type="transport_error")

    class Progress:
        async def load_search_resume_state(self, search_id: str) -> SearchResumeState:
            assert search_id == "search"
            events.append("read-closed")
            return state

        async def commit_discovery_batch(
            self, search_id: str, checkpoint: str | None, batch: LiteratureBatch
        ) -> BatchCommit:
            assert (search_id, checkpoint, batch) == ("search", "opaque", expected_batch)
            assert events == ["read-closed", "provider-returned"]
            events.append("commit")
            return result

        async def record_search_failure(
            self, expected: SearchResumeState, error: LiteratureSourceError
        ) -> None:
            assert expected is state and error is expected_error
            assert events == ["read-closed", "provider-returned"]
            events.append("failure")

    class Provider:
        provider_id = "provider"
        operation_id = "operation"

        async def search(
            self, query: LiteratureQuery, *, checkpoint: str | None = None
        ) -> LiteratureBatch:
            assert query == state.query and checkpoint == "opaque"
            assert events == ["read-closed"]
            events.append("provider-returned")
            if failure:
                raise expected_error
            return expected_batch

    if failure:
        with pytest.raises(LiteratureSourceError) as raised:
            asyncio.run(ingest_one_batch(Progress(), "search", Provider()))
        assert raised.value is expected_error and events[-1] == "failure"
    else:
        assert asyncio.run(ingest_one_batch(Progress(), "search", Provider())) is result
        assert events[-1] == "commit"

    events.clear()
    state = replace(state, status="succeeded")
    assert asyncio.run(ingest_one_batch(Progress(), "search", Provider())) is None
    assert events == ["read-closed"]
    events.clear()
    state = replace(state, operation_id="different", status="partial")
    with pytest.raises(ValueError, match="operation"):
        asyncio.run(ingest_one_batch(Progress(), "search", Provider()))
    assert events == ["read-closed"]
