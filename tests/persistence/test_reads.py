from collections.abc import Coroutine
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid7

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.evidence_brief import render_evidence_brief
from research_atlas.application.ports.literature_source import LiteratureBatch
from research_atlas.application.read_models import Page
from research_atlas.domain.evidence import InsightFinding
from research_atlas.domain.execution import ScreeningDecision
from research_atlas.domain.studies import ResearchRun
from research_atlas.infrastructure.persistence import reads
from research_atlas.infrastructure.persistence.discovery import DiscoveryPersistence
from research_atlas.infrastructure.persistence.evidence import (
    apply_screening_decision,
    record_source_document,
    set_processing_state,
)
from research_atlas.infrastructure.persistence.insights import PostgresInsightPublication
from research_atlas.infrastructure.persistence.runs import create_research_run

from .conftest import run
from .helpers import CONTENT, NOW, document, observation, seed
from .test_insights import SYNTHESIS, Case, accepted_case, insight_for, relationships


async def measured[T](engine: AsyncEngine, call: Coroutine[Any, Any, T]) -> tuple[T, int]:
    statements: list[int] = []

    def before(*args: object) -> None:
        statements.append(1)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        result = await call
        return result, len(statements)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


def test_all_seven_reads_have_constant_statement_counts_at_five_and_ten(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        counts: list[tuple[int, ...]] = []
        for size in (5, 10):
            cases: list[Case] = []
            ids: list[UUID] = []
            for _ in range(size):
                case = await accepted_case(pg_engine, size)
                cases.append(case)
                insight = insight_for(case)
                ids.append(insight.insight_id)
                await PostgresInsightPublication(pg_engine).publish(
                    insight, SYNTHESIS, case.ids, relationships(insight, case), NOW
                )
            progress, c1 = await measured(pg_engine, reads.run_progress(pg_engine, "run"))
            assert progress.processing["discovered"] == (5 if size == 5 else 15)
            sources, c2 = await measured(pg_engine, reads.run_sources(pg_engine, "run", Page(size)))
            assert len(sources) == size
            detail, c3 = await measured(
                pg_engine,
                reads.source_detail(
                    pg_engine,
                    "run",
                    cases[0].document.source_id,
                    documents=Page(size),
                    attempts=Page(size),
                    studies=Page(size),
                    findings=Page(size),
                ),
            )
            assert len(detail.findings) == size
            insight_detail, c4 = await measured(pg_engine, reads.insight_detail(pg_engine, ids[0]))
            assert insight_detail.evidence.findings == size
            expanded, c5 = await measured(
                pg_engine, reads.insight_evidence(pg_engine, ids[0], Page(size))
            )
            assert len(expanded) == size
            context, c6 = await measured(
                pg_engine, reads.study_context(pg_engine, cases[0].study.study_id)
            )
            assert context.content == CONTENT
            outputs, c7 = await measured(pg_engine, reads.output_insights(pg_engine, tuple(ids)))
            assert len(outputs) == size and all(len(item.evidence) == size for item in outputs)
            counts.append((c1, c2, c3, c4, c5, c6, c7))
        assert counts[0] == counts[1] == (4, 1, 6, 2, 1, 1, 3)

    run(scenario())


def test_pages_selection_progress_citations_and_source_run_isolation(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine, "search")
        records = tuple(
            observation(f"W{i}", f"10.1/{i}", title=f"Publication {i}") for i in range(3)
        )
        receipt = await DiscoveryPersistence(pg_engine).commit_discovery_batch(
            "search", None, LiteratureBatch(records, "more", False)
        )
        cases: list[Case] = []
        for source_id in receipt.source_ids:
            assert source_id is not None
            cases.append(await accepted_case(pg_engine, 3, source_id))
        first = cases[0]
        await set_processing_state(pg_engine, "run", first.document.source_id, "extracted")
        await apply_screening_decision(
            pg_engine,
            ScreeningDecision(
                "screen",
                "run",
                first.document.source_id,
                "include",
                first.study.record_provenance,
                ("Eligible",),
            ),
        )
        progress = await reads.run_progress(pg_engine, "run")
        assert progress.request == "Original request"
        assert progress.searches[0].status == "partial"
        assert progress.searches[0].provider_results == 3
        assert progress.searches[0].completed_batches == 1
        assert progress.processing["extracted"] == 1 and progress.processing["discovered"] == 2
        assert progress.screening["include"] == 1 and progress.screening["unscreened"] == 2
        all_sources = await reads.run_sources(pg_engine, "run", Page(100))
        pages = (
            *(await reads.run_sources(pg_engine, "run", Page(2))),
            *(await reads.run_sources(pg_engine, "run", Page(2, 2))),
        )
        assert pages == all_sources
        assert [item.source.source_id for item in pages] == sorted(
            value for value in receipt.source_ids if value is not None
        )
        assert await reads.run_sources(pg_engine, "run", Page(1, 3)) == ()
        for item in pages:
            assert item.discovery_count == 1 and item.first_discovery is not None
            assert item.first_discovery.search_execution_id == "search"
            assert item.source.observation_id is not None
            assert tuple(credit.display_name for credit in item.source.credits) == ("Alice", "Bob")

        # Exact page boundaries for documents, attempts and selected evidence.
        for i in range(2):
            content = CONTENT + str(i).encode()
            await record_source_document(
                pg_engine, document(first.document.source_id, content), content
            )
        replacement = await accepted_case(pg_engine, 4, first.document.source_id)
        whole = await reads.source_detail(
            pg_engine, "run", first.document.source_id, findings=Page(100)
        )
        assert len(whole.documents) == 3 and len(whole.attempts) == 2
        assert whole.studies == (replacement.study,)
        assert whole.selected_extraction == replacement.extraction
        assert {item.finding_id for item in whole.findings} == set(replacement.ids)
        paged = await reads.source_detail(
            pg_engine,
            "run",
            first.document.source_id,
            documents=Page(1, 1),
            attempts=Page(1, 1),
            studies=Page(1, 1),
            findings=Page(2, 2),
        )
        assert paged.documents == whole.documents[1:2] and paged.attempts == whole.attempts[1:2]
        assert paged.studies == () and paged.findings == whole.findings[2:4]
        assert paged.selected_extraction == replacement.extraction
        assert all(item.source_id == first.document.source_id for item in whole.documents)
        assert (
            await reads.study_context(pg_engine, first.study.study_id)
        ).context.study == first.study

        await create_research_run(
            pg_engine, ResearchRun("other", "project", "Unrelated", "queued", NOW)
        )
        assert await reads.run_sources(pg_engine, "other") == ()
        assert not (await reads.run_progress(pg_engine, "other")).searches
        with pytest.raises(ValueError):
            await reads.source_detail(pg_engine, "other", first.document.source_id)

        # Distinct publications are not assumed independent; whole selected bylines are rendered.
        insight = insight_for(replacement)
        selected = (replacement.ids[0], cases[1].ids[0])
        links = tuple(
            InsightFinding(insight.insight_id, value, "supporting", "Explicit judgment")
            for value in selected
        )
        await PostgresInsightPublication(pg_engine).publish(
            insight, SYNTHESIS, selected, links, NOW
        )
        output = await reads.output_insights(pg_engine, (insight.insight_id,))
        assert output[0].detail.evidence.studies == output[0].detail.evidence.sources == 2
        assert "overlap is possible" in output[0].detail.evidence.warnings[0]
        brief = render_evidence_brief(output, title="Evidence Brief")
        assert "Alice; Bob" in brief and "2026" in brief and "Publication 0" in brief
        assert "Publication 1" in brief and "Publication 2" not in brief
        evidence_page = await reads.insight_evidence(pg_engine, insight.insight_id, Page(1))
        evidence_next = await reads.insight_evidence(pg_engine, insight.insight_id, Page(1, 1))
        assert evidence_page + evidence_next == output[0].evidence
        assert await reads.insight_evidence(pg_engine, insight.insight_id, Page(1, 2)) == ()
        with pytest.raises(ValueError, match="published"):
            await reads.output_insights(pg_engine, (insight.insight_id, uuid7()))
        with pytest.raises(ValueError):
            await reads.output_insights(pg_engine, (insight.insight_id, insight.insight_id))

    run(scenario())


def test_explicit_output_order_excludes_unselected_insights(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        ids: list[UUID] = []
        for i in range(3):
            insight = replace(insight_for(case), claim=f"Claim {i}")
            await PostgresInsightPublication(pg_engine).publish(
                insight, SYNTHESIS, case.ids, relationships(insight, case), NOW
            )
            ids.append(insight.insight_id)
        output = await reads.output_insights(pg_engine, (ids[2], ids[0]))
        assert tuple(item.detail.insight.insight_id for item in output) == (ids[2], ids[0])
        text = render_evidence_brief(output, title="Selected output")
        assert "Claim 1" not in text and text.index("Claim 2") < text.index("Claim 0")

    run(scenario())
