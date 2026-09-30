"""Atomic, selected-evidence publication of immutable Insights."""

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.read_models import FindingEvidence, selected_ids
from research_atlas.domain.evidence import Insight, InsightFinding
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.evidence import ImmutableRecordConflict
from research_atlas.infrastructure.persistence.reads import active_evidence
from research_atlas.infrastructure.persistence.serialization import digest, json_value


class PostgresInsightPublication:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def load_evidence(
        self,
        run_id: str,
        finding_ids: tuple[UUID, ...],
    ) -> tuple[FindingEvidence, ...]:
        async with self.engine.begin() as conn:
            return await active_evidence(conn, run_id, finding_ids)

    async def publish(
        self,
        insight: Insight,
        configuration: bytes,
        finding_ids: tuple[UUID, ...],
        relationships: tuple[InsightFinding, ...],
        published_at: datetime,
    ) -> None:
        selected_ids(finding_ids)
        linked = tuple(item.finding_id for item in relationships)
        if len(linked) != len(set(linked)) or set(linked) != set(finding_ids):
            raise ValueError("relationships must account for selected Findings exactly once")
        if any(item.insight_id != insight.insight_id for item in relationships):
            raise ValueError("relationship belongs to another Insight")
        if not any(item.relationship == "supporting" for item in relationships):
            raise ValueError("publication requires explicit supporting evidence")
        if sha256(configuration).hexdigest() != insight.configuration_sha256:
            raise ValueError("synthesis configuration checksum mismatch")
        publication_digest = digest(
            {
                "insight": insight,
                "configuration_hex": configuration.hex(),
                "relationships": sorted(relationships, key=lambda item: item.finding_id),
                "published_at": published_at,
            }
        )
        values = {
            **asdict(insight),
            "record_provenance": json_value(insight.record_provenance),
            "configuration": configuration,
            "publication_digest": publication_digest,
            "published_at": published_at,
        }
        async with self.engine.begin() as conn:
            if (
                await conn.execute(
                    sa.select(s.research_runs.c.run_id).where(
                        s.research_runs.c.run_id == insight.run_id
                    )
                )
            ).scalar_one_or_none() is None:
                raise ValueError("producing run does not exist")
            created = (
                await conn.execute(
                    insert(s.insights)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[s.insights.c.insight_id])
                    .returning(s.insights.c.insight_id)
                )
            ).scalar_one_or_none()
            if created is None:
                current = (
                    (
                        await conn.execute(
                            sa.select(s.insights)
                            .where(s.insights.c.insight_id == insight.insight_id)
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one()
                )
                if (
                    current["publication_status"] == "published"
                    and current["publication_digest"] == publication_digest
                ):
                    # A retry remains valid after later selection changes; it creates no new result.
                    return
                raise ImmutableRecordConflict("Insight UUID already identifies different content")
            await active_evidence(conn, insight.run_id, finding_ids)
            await conn.execute(
                s.insight_findings.insert(), [asdict(item) for item in relationships]
            )
            await conn.execute(
                s.insights.update()
                .where(s.insights.c.insight_id == insight.insight_id)
                .values(publication_status="published")
            )
