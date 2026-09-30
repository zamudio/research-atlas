"""Indexed reconciliation of bounded incoming components, with narrow race recovery."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from research_atlas.application.ports.literature_source import LiteratureRecord
from research_atlas.application.source_identity import ExactSourceKey, exact_source_match_keys
from research_atlas.infrastructure.persistence import schema as s


def incoming_components(records: Sequence[LiteratureRecord]) -> list[list[int]]:
    """Only this bounded page is examined; never load the stored corpus."""
    components: list[tuple[set[ExactSourceKey], list[int]]] = []
    for index, record in enumerate(records):
        keys = set(exact_source_match_keys(record.source))
        indices = [index]
        remaining: list[tuple[set[ExactSourceKey], list[int]]] = []
        for previous_keys, previous_indices in components:
            if keys & previous_keys:
                keys.update(previous_keys)
                indices.extend(previous_indices)
            else:
                remaining.append((previous_keys, previous_indices))
        remaining.append((keys, sorted(indices)))
        components = remaining
    # Common ordering reduces lock contention across overlapping batches.
    return [indices for _, indices in sorted(components, key=lambda item: sorted(item[0]))]


def strong_conflicts(keys: set[ExactSourceKey]) -> list[dict[str, str]]:
    values: dict[str, set[str]] = defaultdict(set)
    for key in keys:
        if key.kind == "external_identifier" and key.namespace in {"doi", "pmid", "pmcid", "arxiv"}:
            values[key.namespace].add(key.value)
    return [
        {"namespace": namespace, "value": value}
        for namespace in sorted(values)
        if len(values[namespace]) > 1
        for value in sorted(values[namespace])
    ]


async def reconcile_component(
    conn: AsyncConnection,
    records: Sequence[LiteratureRecord],
) -> tuple[UUID | None, dict[str, Any] | None]:
    keys = {key for record in records for key in exact_source_match_keys(record.source)}
    if conflicts := strong_conflicts(keys):
        return None, {"reason": "strong_identifiers", "identifiers": conflicts}
    if not keys:
        source_id = uuid7()
        await conn.execute(s.sources.insert().values(source_id=source_id))
        return source_id, None
    key_tuples = [(key.kind, key.namespace, key.value) for key in sorted(keys)]
    lookup = sa.select(s.source_identifiers.c.source_id).where(
        sa.tuple_(
            s.source_identifiers.c.kind,
            s.source_identifiers.c.namespace,
            s.source_identifiers.c.value,
        ).in_(key_tuples)
    )
    # Each lost unique-key race must be re-evaluated from the entire incoming key set.
    for _ in range(len(keys) + 1):
        try:
            async with conn.begin_nested():
                matched = set((await conn.execute(lookup)).scalars())
                if len(matched) > 1:
                    return None, {
                        "reason": "persisted_duplicates",
                        "source_ids": sorted(map(str, matched)),
                    }
                if matched:
                    source_id = next(iter(matched))
                    await conn.execute(
                        sa.select(s.sources.c.source_id)
                        .where(s.sources.c.source_id == source_id)
                        .with_for_update()
                    )
                    stored_rows = (
                        (
                            await conn.execute(
                                sa.select(s.source_identifiers).where(
                                    s.source_identifiers.c.source_id == source_id
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                    stored = {
                        ExactSourceKey(row["kind"], row["namespace"], row["value"])
                        for row in stored_rows
                    }
                    if conflicts := strong_conflicts(keys | stored):
                        return None, {
                            "reason": "strong_identifiers",
                            "identifiers": conflicts,
                            "source_ids": [str(source_id)],
                        }
                    missing = keys - stored
                else:
                    source_id = uuid7()
                    await conn.execute(s.sources.insert().values(source_id=source_id))
                    missing = keys
                for key in sorted(missing):
                    await conn.execute(
                        s.source_identifiers.insert().values(
                            kind=key.kind,
                            namespace=key.namespace,
                            value=key.value,
                            source_id=source_id,
                        )
                    )
                return source_id, None
        except IntegrityError as error:
            if (
                getattr(error.orig, "sqlstate", None) != "23505"
                or getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                != "pk_source_identifiers"
            ):
                raise
    raise RuntimeError("exact identity contention did not settle; retry the unchanged batch")
