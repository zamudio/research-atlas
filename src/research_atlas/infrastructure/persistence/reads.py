"""Seven bounded Core reads and a shared evidence join. No per-item SQL."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from research_atlas.application.read_models import (
    MAX_FINDINGS,
    MAX_INSIGHTS,
    DiscoveryContext,
    EvidenceCounts,
    FindingEvidence,
    InsightDetail,
    InsightEvidence,
    OutputInsight,
    Page,
    RunProgress,
    RunSource,
    SearchProgress,
    SourceDetail,
    StudyContext,
    selected_ids,
)
from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import InsightFinding
from research_atlas.infrastructure.persistence import read_mapping as m
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.evidence import verify_content

DEFAULT_PAGE = Page()

CONTEXT_FROM = (
    s.studies.join(s.extractions, s.studies.c.extraction_id == s.extractions.c.extraction_id)
    .join(
        s.source_documents, s.extractions.c.source_document_id == s.source_documents.c.document_id
    )
    .join(s.sources, s.studies.c.source_id == s.sources.c.source_id)
    .outerjoin(
        s.source_metadata_observations,
        s.sources.c.display_observation_id == s.source_metadata_observations.c.observation_id,
    )
)
CONTEXT_COLUMNS = (
    s.studies.c.study_id,
    s.studies.c.extraction_id,
    s.studies.c.data.label("study_data"),
    s.sources.c.source_id,
    s.sources.c.display_observation_id,
    s.source_metadata_observations.c.reported,
    *(
        s.extractions.c[name].label("extraction_" + name)
        for name in Extraction.__dataclass_fields__
    ),
    *(
        s.source_documents.c[name].label("document_" + name)
        for name in SourceDocument.__dataclass_fields__
    ),
)
FINDING_COLUMNS = (
    s.findings.c.finding_id,
    s.findings.c.anchors,
    s.findings.c.data.label("finding_data"),
)
EVIDENCE_FROM = CONTEXT_FROM.join(s.findings, s.findings.c.study_id == s.studies.c.study_id)


async def active_evidence(
    conn: AsyncConnection,
    run_id: str,
    finding_ids: tuple[UUID, ...],
) -> tuple[FindingEvidence, ...]:
    """Lock membership through validation/publication; immutable evidence needs no row locks."""
    selected_ids(finding_ids)
    rows = (
        (
            await conn.execute(
                sa.select(*CONTEXT_COLUMNS, *FINDING_COLUMNS)
                .select_from(
                    EVIDENCE_FROM.join(
                        s.run_sources, s.run_sources.c.source_id == s.sources.c.source_id
                    )
                )
                .where(
                    s.run_sources.c.run_id == run_id,
                    s.findings.c.finding_id.in_(finding_ids),
                    s.run_sources.c.selected_extraction_id == s.extractions.c.extraction_id,
                    s.extractions.c.status == "accepted",
                )
                .order_by(s.sources.c.source_id, s.findings.c.finding_id)
                .with_for_update(of=s.run_sources)
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(finding_ids):
        raise ValueError("selected Findings must be current accepted evidence for this run")
    by_id = {row["finding_id"]: m.finding_evidence(row) for row in rows}
    return tuple(by_id[value] for value in finding_ids)


async def run_progress(engine: AsyncEngine, run_id: str) -> RunProgress:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ")
        row = (
            (
                await conn.execute(
                    sa.select(s.research_runs).where(s.research_runs.c.run_id == run_id)
                )
            )
            .mappings()
            .one()
        )
        groups = (
            await conn.execute(
                sa.select(
                    s.search_executions.c.provider_id,
                    s.search_executions.c.status,
                    sa.func.count(),
                    sa.func.sum(s.search_executions.c.provider_result_count),
                    sa.func.sum(s.search_executions.c.completed_batches),
                )
                .where(s.search_executions.c.run_id == run_id)
                .group_by(s.search_executions.c.provider_id, s.search_executions.c.status)
                .order_by(s.search_executions.c.provider_id, s.search_executions.c.status)
            )
        ).all()
        processing: dict[str, int] = dict.fromkeys(
            ("discovered", "retrieved", "extracted", "excluded", "unavailable", "failed"), 0
        )
        screening: dict[str, int] = dict.fromkeys(
            ("unscreened", "include", "exclude", "uncertain", "defer", "duplicate"), 0
        )
        for column, target in (
            (s.run_sources.c.processing_state, processing),
            (s.run_sources.c.screening_decision, screening),
        ):
            counts = (
                await conn.execute(
                    sa.select(column, sa.func.count())
                    .where(s.run_sources.c.run_id == run_id)
                    .group_by(column)
                )
            ).all()
            target.update({key or "unscreened": count for key, count in counts})
        return RunProgress(
            row["run_id"],
            row["project_id"],
            row["request"],
            row["status"],
            row["created_at"],
            row["started_at"],
            row["completed_at"],
            tuple(SearchProgress(*group) for group in groups),
            processing,
            screening,
        )


async def _run_sources(
    conn: AsyncConnection,
    run_id: str,
    page: Page,
    source_id: UUID | None = None,
) -> tuple[RunSource, ...]:
    first = (
        sa.select(
            s.source_discoveries.c.search_execution_id,
            s.search_executions.c.provider_id,
            s.source_discoveries.c.discovered_at,
            s.source_discoveries.c.result_position,
        )
        .select_from(
            s.source_discoveries.join(
                s.search_executions,
                s.source_discoveries.c.search_execution_id
                == s.search_executions.c.search_execution_id,
            )
        )
        .where(
            s.source_discoveries.c.run_id == run_id,
            s.source_discoveries.c.source_id == s.run_sources.c.source_id,
        )
        .order_by(s.source_discoveries.c.discovered_at, s.source_discoveries.c.discovery_id)
        .limit(1)
        .correlate(s.run_sources)
        .lateral("first_discovery")
    )
    count = (
        sa.select(sa.func.count())
        .select_from(s.source_discoveries)
        .where(
            s.source_discoveries.c.run_id == run_id,
            s.source_discoveries.c.source_id == s.run_sources.c.source_id,
        )
        .correlate(s.run_sources)
        .scalar_subquery()
    )
    query = (
        sa.select(
            s.run_sources,
            s.sources.c.display_observation_id,
            s.source_metadata_observations.c.reported,
            s.extractions.c.status.label("extraction_status"),
            count.label("discovery_count"),
            first,
        )
        .select_from(
            s.run_sources.join(s.sources, s.sources.c.source_id == s.run_sources.c.source_id)
            .outerjoin(
                s.source_metadata_observations,
                s.sources.c.display_observation_id
                == s.source_metadata_observations.c.observation_id,
            )
            .outerjoin(
                s.extractions,
                s.run_sources.c.selected_extraction_id == s.extractions.c.extraction_id,
            )
            .outerjoin(first, sa.true())
        )
        .where(s.run_sources.c.run_id == run_id)
    )
    if source_id is not None:
        query = query.where(s.run_sources.c.source_id == source_id)
    rows = (
        (
            await conn.execute(
                query.order_by(s.run_sources.c.source_id).limit(page.limit).offset(page.offset)
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        RunSource(
            m.source_display(row),
            row["processing_state"],
            row["screening_decision"],
            row["screening_detail"],
            row["selected_extraction_id"],
            row["extraction_status"],
            row["discovery_count"],
            DiscoveryContext(
                row["search_execution_id"],
                row["provider_id"],
                row["discovered_at"],
                row["result_position"],
            )
            if row["search_execution_id"] is not None
            else None,
        )
        for row in rows
    )


async def run_sources(
    engine: AsyncEngine, run_id: str, page: Page = DEFAULT_PAGE
) -> tuple[RunSource, ...]:
    async with engine.connect() as conn:
        return await _run_sources(conn, run_id, page)


async def source_detail(
    engine: AsyncEngine,
    run_id: str,
    source_id: UUID,
    *,
    documents: Page = DEFAULT_PAGE,
    attempts: Page = DEFAULT_PAGE,
    studies: Page = DEFAULT_PAGE,
    findings: Page = DEFAULT_PAGE,
) -> SourceDetail:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ")
        memberships = await _run_sources(conn, run_id, Page(1), source_id)
        if not memberships:
            raise ValueError("Source does not belong to run")
        membership = memberships[0]
        selected = (
            (
                await conn.execute(
                    sa.select(
                        *(
                            s.extractions.c[name].label("extraction_" + name)
                            for name in Extraction.__dataclass_fields__
                        )
                    ).where(s.extractions.c.extraction_id == membership.selected_extraction_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        docs = (
            (
                await conn.execute(
                    sa.select(
                        *(
                            s.source_documents.c[name].label("document_" + name)
                            for name in SourceDocument.__dataclass_fields__
                        )
                    )
                    .where(s.source_documents.c.source_id == source_id)
                    .order_by(s.source_documents.c.retrieved_at, s.source_documents.c.document_id)
                    .limit(documents.limit)
                    .offset(documents.offset)
                )
            )
            .mappings()
            .all()
        )
        extractions = (
            (
                await conn.execute(
                    sa.select(
                        *(
                            s.extractions.c[name].label("extraction_" + name)
                            for name in Extraction.__dataclass_fields__
                        )
                    )
                    .where(
                        s.extractions.c.source_id == source_id,
                        sa.or_(
                            s.extractions.c.run_id == run_id,
                            s.extractions.c.extraction_id == membership.selected_extraction_id,
                        ),
                    )
                    .order_by(s.extractions.c.extraction_id)
                    .limit(attempts.limit)
                    .offset(attempts.offset)
                )
            )
            .mappings()
            .all()
        )
        study_rows = (
            (
                await conn.execute(
                    sa.select(
                        s.studies.c.study_id,
                        s.studies.c.source_id,
                        s.studies.c.extraction_id,
                        s.studies.c.data.label("study_data"),
                    )
                    .where(
                        s.studies.c.source_id == source_id,
                        s.studies.c.extraction_id == membership.selected_extraction_id,
                    )
                    .order_by(s.studies.c.study_id)
                    .limit(studies.limit)
                    .offset(studies.offset)
                )
            )
            .mappings()
            .all()
        )
        finding_rows = (
            (
                await conn.execute(
                    sa.select(s.findings.c.study_id, *FINDING_COLUMNS)
                    .select_from(
                        s.findings.join(s.studies, s.findings.c.study_id == s.studies.c.study_id)
                    )
                    .where(
                        s.studies.c.source_id == source_id,
                        s.studies.c.extraction_id == membership.selected_extraction_id,
                    )
                    .order_by(s.findings.c.finding_id)
                    .limit(findings.limit)
                    .offset(findings.offset)
                )
            )
            .mappings()
            .all()
        )
        return SourceDetail(
            membership,
            m.extraction_record(selected) if selected is not None else None,
            tuple(map(m.document_record, docs)),
            tuple(map(m.extraction_record, extractions)),
            tuple(map(m.study_record, study_rows)),
            tuple(map(m.finding_record, finding_rows)),
        )


async def _summaries(conn: AsyncConnection, ids: tuple[UUID, ...]) -> dict[UUID, EvidenceCounts]:
    rows = (
        (
            await conn.execute(
                sa.select(
                    s.insight_findings.c.insight_id,
                    sa.func.count().label("findings"),
                    sa.func.count(sa.distinct(s.studies.c.study_id)).label("studies"),
                    sa.func.count(sa.distinct(s.studies.c.source_id)).label("sources"),
                )
                .select_from(
                    s.insight_findings.join(
                        s.findings, s.insight_findings.c.finding_id == s.findings.c.finding_id
                    ).join(s.studies, s.findings.c.study_id == s.studies.c.study_id)
                )
                .where(s.insight_findings.c.insight_id.in_(ids))
                .group_by(s.insight_findings.c.insight_id)
            )
        )
        .mappings()
        .all()
    )
    return {
        row["insight_id"]: EvidenceCounts(row["findings"], row["studies"], row["sources"])
        for row in rows
    }


def _detail(row: sa.RowMapping, counts: EvidenceCounts) -> InsightDetail:
    return InsightDetail(
        m.insight_record(row),
        row["publication_status"],
        row["published_at"],
        row["publication_digest"],
        counts,
    )


async def insight_detail(engine: AsyncEngine, insight_id: UUID) -> InsightDetail:
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ")
        row = (
            (
                await conn.execute(
                    sa.select(*(col for col in s.insights.c if col.name != "configuration")).where(
                        s.insights.c.insight_id == insight_id
                    )
                )
            )
            .mappings()
            .one()
        )
        counts = await _summaries(conn, (insight_id,))
        return _detail(row, counts.get(insight_id, EvidenceCounts(0, 0, 0)))


async def _evidence(
    conn: AsyncConnection,
    ids: tuple[UUID, ...],
    page: Page | None,
) -> tuple[InsightEvidence, ...]:
    query = (
        sa.select(
            *CONTEXT_COLUMNS,
            *FINDING_COLUMNS,
            s.insight_findings.c.insight_id,
            s.insight_findings.c.relationship,
            s.insight_findings.c.rationale,
        )
        .select_from(
            EVIDENCE_FROM.join(
                s.insight_findings, s.insight_findings.c.finding_id == s.findings.c.finding_id
            ).join(s.insights, s.insights.c.insight_id == s.insight_findings.c.insight_id)
        )
        .where(s.insights.c.insight_id.in_(ids), s.insights.c.publication_status == "published")
        .order_by(s.insight_findings.c.insight_id, s.insight_findings.c.finding_id)
    )
    query = (
        query.limit(page.limit).offset(page.offset)
        if page
        else query.limit(MAX_FINDINGS * len(ids) + 1)
    )
    rows = (await conn.execute(query)).mappings().all()
    if page is None and len(rows) > MAX_FINDINGS * len(ids):
        raise ValueError("published evidence exceeds bounded output")
    return tuple(
        InsightEvidence(
            InsightFinding(
                row["insight_id"], row["finding_id"], row["relationship"], row["rationale"]
            ),
            m.finding_evidence(row),
        )
        for row in rows
    )


async def insight_evidence(
    engine: AsyncEngine,
    insight_id: UUID,
    page: Page = DEFAULT_PAGE,
) -> tuple[InsightEvidence, ...]:
    async with engine.connect() as conn:
        return await _evidence(conn, (insight_id,), page)


async def study_context(engine: AsyncEngine, study_id: UUID) -> StudyContext:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    sa.select(*CONTEXT_COLUMNS, s.source_documents.c.content)
                    .select_from(CONTEXT_FROM)
                    .where(s.studies.c.study_id == study_id)
                )
            )
            .mappings()
            .one()
        )
        verify_content(row["content"], row["document_content_sha256"], usable=True)
        return StudyContext(m.evidence_context(row), row["content"])


async def output_insights(
    engine: AsyncEngine, insight_ids: tuple[UUID, ...]
) -> tuple[OutputInsight, ...]:
    selected_ids(insight_ids, MAX_INSIGHTS)
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="REPEATABLE READ")
        rows = (
            (
                await conn.execute(
                    sa.select(*(col for col in s.insights.c if col.name != "configuration")).where(
                        s.insights.c.insight_id.in_(insight_ids),
                        s.insights.c.publication_status == "published",
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(insight_ids):
            raise ValueError("output selection must identify published Insights")
        counts = await _summaries(conn, insight_ids)
        evidence = await _evidence(conn, insight_ids, None)
        by_id = {row["insight_id"]: row for row in rows}
        grouped: dict[UUID, list[InsightEvidence]] = {value: [] for value in insight_ids}
        for item in evidence:
            grouped[item.relationship.insight_id].append(item)
        return tuple(
            OutputInsight(_detail(by_id[value], counts[value]), tuple(grouped[value]))
            for value in insight_ids
        )
