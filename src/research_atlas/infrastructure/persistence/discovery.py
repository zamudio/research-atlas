"""Atomic observations, identity, memberships and checkpoint receipts."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from research_atlas.application.ports.discovery_progress import (
    BatchCommit,
    CheckpointConflict,
    ReplayMismatch,
    SearchResumeState,
)
from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureRecord,
    LiteratureSourceError,
)
from research_atlas.domain.execution import SearchParameter
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.identity import (
    incoming_components,
    reconcile_component,
)
from research_atlas.infrastructure.persistence.serialization import (
    batch_digest,
    batch_key,
    digest,
    json_value,
    reported_content,
)


async def _search(conn: AsyncConnection, search_id: str, *, lock: bool = False) -> sa.RowMapping:
    query = sa.select(s.search_executions).where(
        s.search_executions.c.search_execution_id == search_id
    )
    if lock:
        query = query.with_for_update()
    row = (await conn.execute(query)).mappings().one_or_none()
    if row is None:
        raise ValueError("search execution does not exist")
    return row


def _resume(row: sa.RowMapping) -> SearchResumeState:
    return SearchResumeState(
        row["search_execution_id"],
        row["provider_id"],
        row["operation_id"],
        LiteratureQuery(
            row["exact_query"],
            row["requested_limit"],
            tuple(SearchParameter(item["name"], item["value"]) for item in row["parameters"]),
        ),
        row["checkpoint"],
        row["status"],
        row["completed_batches"],
        row["provider_result_count"],
    )


def _receipt_result(receipt: dict[str, Any]) -> BatchCommit:
    return BatchCommit(
        tuple(UUID(value) for value in receipt["observation_ids"]),
        tuple(UUID(value) if value else None for value in receipt["source_ids"]),
        receipt["next_checkpoint"],
        receipt["exhausted"],
        tuple(receipt["conflicted_positions"]),
    )


async def _observation(
    conn: AsyncConnection,
    search_id: str,
    key: str,
    position: int,
    record: LiteratureRecord,
    source_id: UUID | None,
    conflict: dict[str, Any] | None,
) -> UUID:
    provenance = record.source.provider_provenance[0]
    reported = reported_content(record)
    publication_id = (provenance.provider_record_id or "").strip() or None
    statement = insert(s.source_metadata_observations).values(
        observation_id=record.observation_id,
        source_id=source_id,
        provider=provenance.provider.strip().lower(),
        provider_record_id=publication_id,
        retrieved_at=provenance.retrieved_at,
        last_seen_at=provenance.retrieved_at,
        reported=reported,
        content_hash=digest(reported),
        search_execution_id=search_id,
        input_batch_key=key,
        page_position=position,
        conflict=conflict,
    )
    columns = (
        [
            s.source_metadata_observations.c.provider,
            s.source_metadata_observations.c.provider_record_id,
            s.source_metadata_observations.c.content_hash,
        ]
        if publication_id
        else [
            s.source_metadata_observations.c.search_execution_id,
            s.source_metadata_observations.c.input_batch_key,
            s.source_metadata_observations.c.page_position,
        ]
    )
    predicate = (
        s.source_metadata_observations.c.provider_record_id.is_not(None)
        if publication_id
        else s.source_metadata_observations.c.provider_record_id.is_(None)
    )
    row = (
        (
            await conn.execute(
                statement.on_conflict_do_update(
                    index_elements=columns,
                    index_where=predicate,
                    set_={
                        "last_seen_at": sa.func.greatest(
                            s.source_metadata_observations.c.last_seen_at,
                            statement.excluded.last_seen_at,
                        )
                    },
                ).returning(s.source_metadata_observations)
            )
        )
        .mappings()
        .one()
    )
    # Reusing a snapshot cannot erase an earlier resolved attribution. Contextual conflicts
    # are also retained in this search's batch receipt, with a null result mapping.
    if source_id is not None and row["source_id"] is None:
        await conn.execute(
            s.source_metadata_observations.update()
            .where(s.source_metadata_observations.c.observation_id == row["observation_id"])
            .values(source_id=source_id, conflict=None)
        )
    elif source_id is not None and row["source_id"] != source_id:
        raise ValueError("snapshot attribution disagrees with authoritative Source identity")
    return row["observation_id"]


class DiscoveryPersistence:
    """Three concrete discovery operations; caller owns this engine's lifetime."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def load_search_resume_state(self, search_id: str) -> SearchResumeState:
        async with self.engine.connect() as conn:
            return _resume(await _search(conn, search_id))

    async def commit_discovery_batch(
        self,
        search_id: str,
        checkpoint: str | None,
        batch: LiteratureBatch,
    ) -> BatchCommit:
        payload_digest = batch_digest(batch)
        json_value(batch)  # Reject non-JSON details and naive timestamps before persistence.
        key = batch_key(checkpoint)
        async with self.engine.begin() as conn:
            search = await _search(conn, search_id, lock=True)
            receipts: dict[str, Any] = dict(search["batch_receipts"])
            if key in receipts:
                if receipts[key]["digest"] != payload_digest:
                    raise ReplayMismatch("committed batch has different validated content")
                return _receipt_result(receipts[key])
            if (
                search["checkpoint"] != checkpoint
                or search["status"] in {"succeeded", "cancelled"}
                or batch.start_position != search["provider_result_count"]
            ):
                raise CheckpointConflict("search does not expect this checkpoint/position")
            if len(batch.records) > search["requested_limit"]:
                raise ValueError("batch exceeds the persisted per-page limit")
            if not batch.exhausted and batch.next_checkpoint == checkpoint:
                raise CheckpointConflict("next checkpoint must advance")
            source_ids: list[UUID | None] = [None] * len(batch.records)
            conflicts: dict[int, dict[str, Any]] = {}
            for indices in incoming_components(batch.records):
                source_id, conflict = await reconcile_component(
                    conn, [batch.records[i] for i in indices]
                )
                for index in indices:
                    source_ids[index] = source_id
                    if conflict is not None:
                        conflicts[index] = conflict
            observation_ids: list[UUID] = []
            for index, record in enumerate(batch.records):
                source_id = source_ids[index]
                observation_id = await _observation(
                    conn, search_id, key, index + 1, record, source_id, conflicts.get(index)
                )
                observation_ids.append(observation_id)
                if source_id is None:
                    continue
                await conn.execute(
                    s.sources.update()
                    .where(
                        s.sources.c.source_id == source_id,
                        s.sources.c.display_observation_id.is_(None),
                    )
                    .values(display_observation_id=observation_id)
                )
                await conn.execute(
                    insert(s.run_sources)
                    .values(run_id=search["run_id"], source_id=source_id)
                    .on_conflict_do_nothing()
                )
                provenance = record.source.provider_provenance[0]
                await conn.execute(
                    insert(s.source_discoveries)
                    .values(
                        discovery_id=str(uuid7()),
                        search_execution_id=search_id,
                        run_id=search["run_id"],
                        source_id=source_id,
                        observation_id=observation_id,
                        discovered_at=datetime.now(UTC),
                        result_position=batch.start_position + index + 1,
                        provider_record_id=provenance.provider_record_id
                        if provenance.provider.strip().lower()
                        == search["provider_id"].strip().lower()
                        else None,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            s.source_discoveries.c.search_execution_id,
                            s.source_discoveries.c.source_id,
                        ]
                    )
                )
            receipt = json_value(
                {
                    "digest": payload_digest,
                    "observation_ids": observation_ids,
                    "source_ids": source_ids,
                    "next_checkpoint": batch.next_checkpoint,
                    "exhausted": batch.exhausted,
                    "conflicted_positions": sorted(conflicts),
                    "conflicts": {str(index): detail for index, detail in conflicts.items()},
                }
            )
            receipts[key] = receipt
            await conn.execute(
                s.search_executions.update()
                .where(s.search_executions.c.search_execution_id == search_id)
                .values(
                    checkpoint=batch.next_checkpoint,
                    status="succeeded" if batch.exhausted else "partial",
                    completed_at=datetime.now(UTC),
                    provider_result_count=search["provider_result_count"] + len(batch.records),
                    completed_batches=search["completed_batches"] + 1,
                    batch_receipts=receipts,
                    error_type=None,
                    error_status_code=None,
                    error_message=None,
                )
            )
            return _receipt_result(receipt)

    async def record_search_failure(
        self,
        expected: SearchResumeState,
        error: LiteratureSourceError,
    ) -> None:
        async with self.engine.begin() as conn:
            search = await _search(conn, expected.search_execution_id, lock=True)
            if (
                search["checkpoint"] != expected.checkpoint
                or search["completed_batches"] != expected.completed_batches
                or search["status"] in {"succeeded", "cancelled"}
            ):
                raise CheckpointConflict("failure belongs to an outdated search invocation")
            safe_type = (
                error.error_type
                if error.error_type
                in {
                    "http_error",
                    "http_status",
                    "transport_error",
                    "malformed_response",
                    "invalid_checkpoint",
                    "http",
                    "transport",
                }
                else "provider_error"
            )
            await conn.execute(
                s.search_executions.update()
                .where(s.search_executions.c.search_execution_id == expected.search_execution_id)
                .values(
                    status="partial" if search["completed_batches"] else "failed",
                    completed_at=datetime.now(UTC),
                    error_type=safe_type,
                    error_status_code=error.status_code,
                    error_message="Provider request failed; retry the durable input checkpoint.",
                )
            )
