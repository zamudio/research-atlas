import asyncio
from dataclasses import replace
from typing import Any
from uuid import uuid7

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.dml import Insert

from research_atlas.application.durable_ingestion import ingest_one_batch
from research_atlas.application.ports.discovery_progress import CheckpointConflict, ReplayMismatch
from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureSourceError,
)
from research_atlas.domain.execution import SearchExecution, SearchParameter
from research_atlas.domain.studies import ExternalIdentifier, ResearchRun
from research_atlas.infrastructure.persistence import discovery
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.discovery import DiscoveryPersistence
from research_atlas.infrastructure.persistence.runs import (
    create_research_run,
    start_search_execution,
)

from .conftest import run
from .helpers import NOW, count, observation, seed


def test_empty_database_migration_and_alembic_drift(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        async with pg_engine.connect() as conn:

            def check(sync: sa.Connection) -> None:
                assert set(sa.inspect(sync).get_table_names()) == {
                    *s.metadata.tables,
                    "alembic_version",
                }
                config = Config("alembic.ini")
                config.attributes["connection"] = sync
                command.check(config)

            await conn.run_sync(check)

    run(scenario())


@pytest.mark.parametrize("by_provider", [False, True])
def test_exact_keys_reuse_stored_source(pg_engine: AsyncEngine, by_provider: bool) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a", "b")
        store = DiscoveryPersistence(pg_engine)
        first = observation("W1", None if by_provider else "https://doi.org/10.1/A")
        second = observation("W1" if by_provider else "W2", None if by_provider else "10.1/a")
        left = await store.commit_discovery_batch("a", None, LiteratureBatch((first,), None, True))
        right = await store.commit_discovery_batch(
            "b", None, LiteratureBatch((second,), None, True)
        )
        assert left.source_ids == right.source_ids
        assert await count(pg_engine, s.sources) == 1
        assert await count(pg_engine, s.run_sources) == 1
        assert await count(pg_engine, s.source_discoveries) == 2

    run(scenario())


def test_unknown_keys_and_keyless_replay_remain_distinct(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a")
        store = DiscoveryPersistence(pg_engine)
        records = tuple(
            observation(None, None, extra=(ExternalIdentifier("unknown", "same"),))
            for _ in range(2)
        )
        batch = LiteratureBatch(records, None, True)
        result = await store.commit_discovery_batch("a", None, batch)
        assert len(set(result.source_ids)) == 2
        assert await store.commit_discovery_batch("a", None, batch) == result
        assert await count(pg_engine, s.source_identifiers) == 0
        assert await count(pg_engine, s.source_metadata_observations) == 2

    run(scenario())


def test_conflict_component_does_not_discard_unrelated_source(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a")
        records = (
            observation("shared", "10.1/a"),
            observation("shared", "10.1/b"),
            observation("other", "10.1/c"),
        )
        result = await DiscoveryPersistence(pg_engine).commit_discovery_batch(
            "a", None, LiteratureBatch(records, None, True)
        )
        assert result.source_ids[:2] == (None, None)
        assert result.source_ids[2] is not None
        assert result.conflicted_positions == (0, 1)
        assert await count(pg_engine, s.sources) == 1
        assert await count(pg_engine, s.source_metadata_observations) == 3
        assert await count(pg_engine, s.source_discoveries) == 1

    run(scenario())


def test_persisted_duplicate_sources_are_quarantined_without_rewriting(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a", "b", "bridge")
        store = DiscoveryPersistence(pg_engine)
        await store.commit_discovery_batch(
            "a", None, LiteratureBatch((observation("W1", "10.1/a"),), None, True)
        )
        await store.commit_discovery_batch(
            "b",
            None,
            LiteratureBatch(
                (observation("W2", None, extra=(ExternalIdentifier("pmid", "2"),)),), None, True
            ),
        )
        bridge = observation("W3", "10.1/a", extra=(ExternalIdentifier("pmid", "2"),))
        result = await store.commit_discovery_batch(
            "bridge", None, LiteratureBatch((bridge,), None, True)
        )
        assert result.source_ids == (None,)
        assert await count(pg_engine, s.sources) == 2
        assert await count(pg_engine, s.source_discoveries) == 2

    run(scenario())


@pytest.mark.parametrize("disagree", [False, True])
def test_real_unique_key_race_rechecks_complete_strong_keys(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    disagree: bool,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a", "b")
        barrier = asyncio.Barrier(2)
        seen: set[AsyncConnection] = set()
        execute = AsyncConnection.execute

        async def synchronized(
            conn: AsyncConnection, statement: Any, *args: Any, **kwargs: Any
        ) -> Any:
            if (
                isinstance(statement, Insert)
                and statement.table.name == "source_identifiers"
                and conn not in seen
            ):
                seen.add(conn)
                await asyncio.wait_for(barrier.wait(), timeout=10)
            return await execute(conn, statement, *args, **kwargs)

        monkeypatch.setattr(AsyncConnection, "execute", synchronized)
        store = DiscoveryPersistence(pg_engine)
        left = observation(extra=(ExternalIdentifier("pmid", "1"),))
        right = observation(extra=(ExternalIdentifier("pmid", "2" if disagree else "1"),))
        results = await asyncio.wait_for(
            asyncio.gather(
                store.commit_discovery_batch("a", None, LiteratureBatch((left,), None, True)),
                store.commit_discovery_batch("b", None, LiteratureBatch((right,), None, True)),
            ),
            timeout=20,
        )
        assert len(seen) == 2  # Both transactions reached key insertion before either committed.
        assert await count(pg_engine, s.sources) == 1
        if disagree:
            assert sum(result.source_ids == (None,) for result in results) == 1
            assert await count(pg_engine, s.source_discoveries) == 1
        else:
            assert results[0].source_ids == results[1].source_ids
        assert await count(pg_engine, s.source_identifiers) == 3

    run(scenario())


def test_snapshot_dedup_display_stability_order_and_observation_attribution(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a", "b", "c")
        store = DiscoveryPersistence(pg_engine)
        first = await store.commit_discovery_batch(
            "a", None, LiteratureBatch((observation(),), None, True)
        )
        repeated = await store.commit_discovery_batch(
            "b", None, LiteratureBatch((observation(),), None, True)
        )
        changed = await store.commit_discovery_batch(
            "c", None, LiteratureBatch((observation(title="Changed"),), None, True)
        )
        assert first.observation_ids == repeated.observation_ids
        assert changed.observation_ids != first.observation_ids
        async with pg_engine.connect() as conn:
            assert (
                await conn.execute(sa.select(s.sources.c.display_observation_id))
            ).scalar_one() == first.observation_ids[0]
            snapshot = (
                await conn.execute(
                    sa.select(s.source_metadata_observations.c.reported).where(
                        s.source_metadata_observations.c.observation_id == first.observation_ids[0]
                    )
                )
            ).scalar_one()
            assert [credit["display_name"] for credit in snapshot["credits"]] == ["Alice", "Bob"]
            attributed = (
                await conn.execute(
                    sa.select(s.source_discoveries.c.observation_id).where(
                        s.source_discoveries.c.search_execution_id == "c"
                    )
                )
            ).scalar_one()
            assert attributed == changed.observation_ids[0]
        assert await count(pg_engine, s.source_metadata_observations) == 2

    run(scenario())


def test_batch_replay_mismatch_and_stale_checkpoint(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a")
        store = DiscoveryPersistence(pg_engine)
        batch = LiteratureBatch((observation(),), "opaque-next", False)
        original = await store.commit_discovery_batch("a", None, batch)
        assert (
            await store.commit_discovery_batch("a", None, replace(batch, records=(observation(),)))
            == original
        )
        with pytest.raises(ReplayMismatch):
            await store.commit_discovery_batch(
                "a", None, replace(batch, records=(observation(title="changed"),))
            )
        with pytest.raises(CheckpointConflict):
            await store.commit_discovery_batch("a", "stale", LiteratureBatch((), None, True, 1))
        state = await store.load_search_resume_state("a")
        assert (state.checkpoint, state.provider_result_count, state.completed_batches) == (
            "opaque-next",
            1,
            1,
        )

    run(scenario())


def test_two_callers_cannot_advance_same_search_twice(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a")
        store = DiscoveryPersistence(pg_engine)
        batch = LiteratureBatch((observation(),), "next", False)
        left, right = await asyncio.gather(
            store.commit_discovery_batch("a", None, batch),
            store.commit_discovery_batch("a", None, batch),
        )
        assert left == right
        assert (await store.load_search_resume_state("a")).completed_batches == 1
        assert await count(pg_engine, s.source_discoveries) == 1

    run(scenario())


def test_transaction_failure_restores_input_checkpoint_and_all_batch_writes(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a")
        store = DiscoveryPersistence(pg_engine)
        original = vars(discovery)["_observation"]

        async def fail_second(*args: Any, **kwargs: Any) -> Any:
            result = await original(*args, **kwargs)
            if args[3] == 2:
                raise ValueError("injected transaction failure")
            return result

        monkeypatch.setattr(discovery, "_observation", fail_second)
        batch = LiteratureBatch((observation(), observation("W2", "10.1/b")), "next", False)
        with pytest.raises(ValueError, match="injected"):
            await store.commit_discovery_batch("a", None, batch)
        assert (await store.load_search_resume_state("a")).checkpoint is None
        assert await count(pg_engine, s.sources) == 0
        assert await count(pg_engine, s.source_metadata_observations) == 0
        monkeypatch.setattr(discovery, "_observation", original)
        await store.commit_discovery_batch("a", None, batch)
        assert (await store.load_search_resume_state("a")).provider_result_count == 2

    run(scenario())


def test_later_provider_failure_keeps_prior_commits_and_safe_resume(pg_engine: AsyncEngine) -> None:
    class Provider:
        provider_id = "openalex"
        operation_id = "openalex.search"

        async def search(
            self, query: LiteratureQuery, *, checkpoint: str | None = None
        ) -> LiteratureBatch:
            assert checkpoint == "next"
            raise LiteratureSourceError(
                "secret=do-not-persist", error_type="http_status", status_code=503
            )

    async def scenario() -> None:
        await seed(pg_engine, "a")
        store = DiscoveryPersistence(pg_engine)
        await store.commit_discovery_batch(
            "a", None, LiteratureBatch((observation(),), "next", False)
        )
        with pytest.raises(LiteratureSourceError):
            await ingest_one_batch(store, "a", Provider())
        resumed = await store.load_search_resume_state("a")
        assert (resumed.status, resumed.checkpoint, resumed.provider_result_count) == (
            "partial",
            "next",
            1,
        )
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.search_executions))).mappings().one()
            assert row["error_type"] == "http_status" and row["error_status_code"] == 503
            assert "secret" not in row["error_message"]
        await store.commit_discovery_batch("a", "next", LiteratureBatch((), None, True, 1))
        with pytest.raises(CheckpointConflict):
            await store.record_search_failure(
                resumed, LiteratureSourceError("stale", error_type="transport_error")
            )
        assert (await store.load_search_resume_state("a")).status == "succeeded"

    run(scenario())


def test_initial_failure_retries_exact_ordered_parameters(pg_engine: AsyncEngine) -> None:
    parameters = (SearchParameter("filter", "first"), SearchParameter("filter", "second"))

    class Provider:
        provider_id = "openalex"
        operation_id = "openalex.search"
        calls = 0

        async def search(
            self, query: LiteratureQuery, *, checkpoint: str | None = None
        ) -> LiteratureBatch:
            assert query.parameters == parameters and checkpoint is None
            self.calls += 1
            if self.calls == 1:
                raise LiteratureSourceError(
                    "failed before first page", error_type="transport_error"
                )
            return LiteratureBatch((observation(),), None, True)

    async def scenario() -> None:
        await seed(pg_engine)
        await start_search_execution(
            pg_engine,
            SearchExecution(
                "search",
                "run",
                "openalex",
                "openalex.search",
                "query",
                parameters,
                10,
                NOW,
                None,
                "running",
            ),
        )
        store = DiscoveryPersistence(pg_engine)
        provider = Provider()
        with pytest.raises(LiteratureSourceError):
            await ingest_one_batch(store, "search", provider)
        state = await store.load_search_resume_state("search")
        assert (state.status, state.checkpoint, state.completed_batches) == ("failed", None, 0)
        assert await count(pg_engine, s.sources) == 0
        result = await ingest_one_batch(store, "search", provider)
        assert result is not None and result.source_ids[0] is not None
        assert (await store.load_search_resume_state("search")).status == "succeeded"

    run(scenario())


@pytest.mark.parametrize("mismatch", ["observation", "run"])
def test_discovery_foreign_keys_reject_wrong_attribution(
    pg_engine: AsyncEngine, mismatch: str
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "a", "b")
        result = await DiscoveryPersistence(pg_engine).commit_discovery_batch(
            "a", None, LiteratureBatch((observation(), observation("W2", "10.1/b")), None, True)
        )
        if mismatch == "run":
            await create_research_run(
                pg_engine, ResearchRun("other", "project", "other", "queued", NOW)
            )
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.run_sources.insert().values(run_id="other", source_id=result.source_ids[0])
                )
        with pytest.raises(IntegrityError) as rejected:
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.source_discoveries.insert().values(
                        discovery_id=str(uuid7()),
                        search_execution_id="b",
                        run_id="other" if mismatch == "run" else "run",
                        source_id=result.source_ids[0],
                        observation_id=result.observation_ids[
                            1 if mismatch == "observation" else 0
                        ],
                        discovered_at=NOW,
                        result_position=1,
                    )
                )
        expected_constraint = "fk_source_discoveries_" + (
            "search_execution_id" if mismatch == "run" else "observation_id"
        )
        assert (
            getattr(getattr(rejected.value.orig, "diag", None), "constraint_name", None)
            == expected_constraint
        )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.sources.update()
                    .where(s.sources.c.source_id == result.source_ids[0])
                    .values(display_observation_id=result.observation_ids[1])
                )

    run(scenario())
