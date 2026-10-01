import asyncio
import json
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from uuid import UUID, uuid7

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from research_atlas.application.evidence_brief import render_evidence_brief
from research_atlas.application.read_models import FindingEvidence
from research_atlas.application.synthesis import synthesize_insight
from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord, Insight, InsightFinding
from research_atlas.domain.studies import ResearchRun, StudyRecord
from research_atlas.infrastructure.persistence import insights as insight_store
from research_atlas.infrastructure.persistence import reads
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.evidence import (
    ImmutableRecordConflict,
    publish_accepted_extraction,
    record_source_document,
    select_run_source_extraction,
)
from research_atlas.infrastructure.persistence.insights import PostgresInsightPublication
from research_atlas.infrastructure.persistence.runs import create_research_run
from research_atlas.infrastructure.persistence.serialization import json_value
from tests.unit.test_synthesis import proposal

from .conftest import run
from .helpers import CONFIGURATION, CONTENT, NOW, count, document, evidence, seed, source

SYNTHESIS = b"Assess explicit evidence; retain contradictions, uncertainty and limitations."


@dataclass(frozen=True)
class Case:
    document: SourceDocument
    extraction: Extraction
    study: StudyRecord
    findings: tuple[FindingRecord, ...]

    @property
    def ids(self) -> tuple[UUID, ...]:
        return tuple(item.finding_id for item in self.findings)


async def accepted_case(
    engine: AsyncEngine,
    size: int = 3,
    source_id: UUID | None = None,
    content: bytes = CONTENT,
) -> Case:
    doc = document(source_id or await source(engine), content)
    doc = replace(doc, document_id=await record_source_document(engine, doc, content))
    extraction, study, finding = evidence(doc)
    findings = tuple(
        replace(finding, finding_id=uuid7(), result_summary=f"No change {i}") for i in range(size)
    )
    await publish_accepted_extraction(engine, extraction, CONFIGURATION, (study,), findings)
    await select_run_source_extraction(engine, "run", doc.source_id, extraction.extraction_id)
    return Case(doc, extraction, study, findings)


def insight_for(case: Case) -> Insight:
    return Insight(
        uuid7(),
        "run",
        "Available evidence did not demonstrate change",
        sha256(SYNTHESIS).hexdigest(),
        case.study.record_provenance,
        ("Limited sample",),
        ("Results uncertain",),
        ("Adults in a lab",),
    )


def relationships(insight: Insight, case: Case) -> tuple[InsightFinding, ...]:
    return tuple(
        InsightFinding(insight.insight_id, value, "supporting", "Explicit null evidence")
        for value in case.ids
    )


@pytest.mark.parametrize(
    "mode",
    [
        "empty",
        "no_support",
        "unknown",
        "outside_run",
        "unselected",
        "duplicate",
        "omitted",
        "introduced",
        "no_rationale",
        "bad_digest",
        "unknown_run",
    ],
)
def test_invalid_publication_is_atomic(pg_engine: AsyncEngine, mode: str) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        insight = insight_for(case)
        ids = case.ids
        links = relationships(insight, case)
        configuration = SYNTHESIS
        if mode == "empty":
            ids, links = (), ()
        elif mode == "no_support":
            links = tuple(replace(link, relationship="contextual") for link in links)
        elif mode == "unknown":
            ids = (uuid7(),)
            links = (replace(links[0], finding_id=ids[0]),)
        elif mode in {"outside_run", "unknown_run"}:
            if mode == "outside_run":
                await create_research_run(
                    pg_engine, ResearchRun("other", "project", "Other request", "queued", NOW)
                )
            insight = replace(
                insight,
                run_id="other",
                record_provenance=replace(insight.record_provenance, created_in_run_id="other"),
            )
        elif mode == "unselected":
            await accepted_case(pg_engine, source_id=case.document.source_id)
        elif mode == "duplicate":
            links += (links[0],)
        elif mode == "omitted":
            links = links[:-1]
        elif mode == "introduced":
            links += (replace(links[0], finding_id=uuid7()),)
        elif mode == "bad_digest":
            configuration = b"changed"
        store = PostgresInsightPublication(pg_engine)
        with pytest.raises(ValueError):
            if mode == "no_rationale":
                links = (replace(relationships(insight, case)[0], rationale=" "),)
            await store.publish(insight, configuration, ids, links, NOW)
        assert await count(pg_engine, s.insights) == 0
        assert await count(pg_engine, s.insight_findings) == 0
        if mode in {"unknown", "outside_run", "unselected", "unknown_run"}:
            with pytest.raises(ValueError):
                await store.load_evidence(insight.run_id, ids)

    run(scenario())


@pytest.mark.parametrize("mode", ["omitted", "introduced", "no_rationale", "duplicate"])
def test_invalid_generated_proposal_never_publishes(pg_engine: AsyncEngine, mode: str) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)

        class Synthesizer:
            async def propose(
                self, evidence: tuple[FindingEvidence, ...], configuration: bytes
            ) -> str:
                assert tuple(item.finding.finding_id for item in evidence) == case.ids
                data = proposal(case.ids)
                if mode == "omitted":
                    data["relationships"].pop()
                elif mode == "introduced":
                    data["relationships"][0]["finding_id"] = str(uuid7())
                elif mode == "duplicate":
                    data["relationships"][1] = data["relationships"][0]
                else:
                    data["relationships"][0]["rationale"] = " "
                return json.dumps(data)

        with pytest.raises(ValueError):
            await synthesize_insight(
                PostgresInsightPublication(pg_engine),
                Synthesizer(),
                run_id="run",
                insight_id=uuid7(),
                finding_ids=case.ids,
                configuration=SYNTHESIS,
                provenance=case.study.record_provenance,
                published_at=NOW,
            )
        assert await count(pg_engine, s.insights) == 0
        assert await count(pg_engine, s.insight_findings) == 0

    run(scenario())


def test_mixed_null_evidence_history_retry_and_brief(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        store = PostgresInsightPublication(pg_engine)
        insight = insight_for(case)
        roles = ("supporting", "contradicting", "contextual")
        links = tuple(
            InsightFinding(insight.insight_id, value, role, f"Explicit {role} judgment")
            for value, role in zip(case.ids, roles, strict=True)
        )
        await store.publish(insight, SYNTHESIS, case.ids, links, NOW)
        await accepted_case(
            pg_engine,
            source_id=case.document.source_id,
            content=CONTENT + b" Revised source content.",
        )
        await store.publish(insight, SYNTHESIS, case.ids, links, NOW)
        detail = await reads.insight_detail(pg_engine, insight.insight_id)
        assert detail.insight == insight and detail.evidence.findings == 3
        assert detail.evidence.studies == detail.evidence.sources == 1
        assert "share a Study" in detail.evidence.warnings[0]
        expanded = await reads.insight_evidence(pg_engine, insight.insight_id)
        assert {item.relationship.relationship for item in expanded} == set(roles)
        assert all(item.evidence.finding.direction == "null" for item in expanded)
        assert all(item.evidence.context.extraction == case.extraction for item in expanded)
        assert {item.evidence.finding.finding_id for item in expanded} == set(case.ids)
        context = await reads.study_context(pg_engine, case.study.study_id)
        assert context.content == CONTENT and context.context.document == case.document
        outputs = await reads.output_insights(pg_engine, (insight.insight_id,))
        brief = render_evidence_brief(outputs, title="Null evidence")
        for required in (
            "Supporting evidence",
            "Contradictory evidence",
            "Contextual evidence",
            "Results uncertain",
            "Explicit contradicting judgment",
            *map(str, case.ids),
        ):
            assert required in brief
        with pytest.raises(ImmutableRecordConflict):
            await store.publish(replace(insight, claim="Changed"), SYNTHESIS, case.ids, links, NOW)
        assert await count(pg_engine, s.insights) == 1
        assert await count(pg_engine, s.insight_findings) == 3
        async with pg_engine.connect() as conn:
            assert (
                await conn.execute(sa.select(s.insights.c.configuration))
            ).scalar_one() == SYNTHESIS

    run(scenario())


@pytest.mark.parametrize(
    "change", ["claim", "evidence", "configuration", "provenance", "rationale"]
)
def test_same_uuid_different_content_fails(pg_engine: AsyncEngine, change: str) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        store = PostgresInsightPublication(pg_engine)
        insight = insight_for(case)
        links, ids, config = relationships(insight, case), case.ids, SYNTHESIS
        await store.publish(insight, config, ids, links, NOW)
        if change == "claim":
            insight = replace(insight, claim="Another claim")
        elif change == "evidence":
            ids, links = ids[:1], links[:1]
        elif change == "configuration":
            config = b"new instructions"
            insight = replace(insight, configuration_sha256=sha256(config).hexdigest())
        elif change == "provenance":
            insight = replace(
                insight,
                record_provenance=replace(insight.record_provenance, reviewer="Another reviewer"),
            )
        else:
            links = (replace(links[0], rationale="Changed appraisal"), *links[1:])
        with pytest.raises(ImmutableRecordConflict):
            await store.publish(insight, config, ids, links, NOW)
        assert await count(pg_engine, s.insights) == 1
        assert await count(pg_engine, s.insight_findings) == 3

    run(scenario())


@pytest.mark.parametrize(
    "mutation", ["insight_update", "insight_delete", "link_update", "link_delete", "link_insert"]
)
def test_database_rejects_mutating_published_history(pg_engine: AsyncEngine, mutation: str) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        store = PostgresInsightPublication(pg_engine)
        insight = insight_for(case)
        await store.publish(insight, SYNTHESIS, case.ids[:1], relationships(insight, case)[:1], NOW)
        with pytest.raises(DBAPIError, match="immutable"):
            async with pg_engine.begin() as conn:
                if mutation == "insight_update":
                    await conn.execute(s.insights.update().values(claim="Overwritten"))
                elif mutation == "insight_delete":
                    await conn.execute(s.insights.delete())
                elif mutation == "link_update":
                    await conn.execute(s.insight_findings.update().values(rationale="Changed"))
                elif mutation == "link_delete":
                    await conn.execute(s.insight_findings.delete())
                else:
                    await conn.execute(
                        s.insight_findings.insert().values(
                            insight_id=insight.insight_id,
                            finding_id=case.ids[1],
                            relationship="contextual",
                            rationale="Added after publication",
                        )
                    )
        assert await count(pg_engine, s.insights) == await count(pg_engine, s.insight_findings) == 1

    run(scenario())


def test_selection_change_during_synthesis_rejected_at_publication(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)

        class Synthesizer:
            async def propose(
                self, evidence: tuple[FindingEvidence, ...], configuration: bytes
            ) -> str:
                assert evidence[0].context.extraction == case.extraction
                await accepted_case(pg_engine, source_id=case.document.source_id)
                return json.dumps(proposal(case.ids))

        with pytest.raises(ValueError, match="current accepted"):
            await synthesize_insight(
                PostgresInsightPublication(pg_engine),
                Synthesizer(),
                run_id="run",
                insight_id=uuid7(),
                finding_ids=case.ids,
                configuration=SYNTHESIS,
                provenance=case.study.record_provenance,
                published_at=NOW,
            )
        assert await count(pg_engine, s.insights) == await count(pg_engine, s.insight_findings) == 0

    run(scenario())


def test_publication_locks_selection_until_commit(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        other = await accepted_case(pg_engine, source_id=case.document.source_id)
        await select_run_source_extraction(
            pg_engine, "run", case.document.source_id, case.extraction.extraction_id
        )
        locked, release = asyncio.Event(), asyncio.Event()
        original = insight_store.active_evidence

        async def hold(
            conn: AsyncConnection, run_id: str, finding_ids: tuple[UUID, ...]
        ) -> tuple[FindingEvidence, ...]:
            packet = await original(conn, run_id, finding_ids)
            locked.set()
            await release.wait()
            return packet

        monkeypatch.setattr(insight_store, "active_evidence", hold)
        insight = insight_for(case)
        publishing = asyncio.create_task(
            PostgresInsightPublication(pg_engine).publish(
                insight, SYNTHESIS, case.ids, relationships(insight, case), NOW
            )
        )
        try:
            await asyncio.wait_for(locked.wait(), timeout=10)
            selecting = asyncio.create_task(
                select_run_source_extraction(
                    pg_engine, "run", case.document.source_id, other.extraction.extraction_id
                )
            )
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(selecting), timeout=0.1)
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(publishing, selecting), timeout=10)
        detail = await reads.source_detail(pg_engine, "run", case.document.source_id)
        assert detail.selected_extraction == other.extraction
        historical = await reads.insight_evidence(pg_engine, insight.insight_id)
        assert all(item.evidence.context.extraction == case.extraction for item in historical)

    run(scenario())


def test_stage3_rows_upgrade_as_drafts_without_invented_publication(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        # Seed evidence using today's writer before dropping columns unavailable at Stage 3.
        # The retained evidence/configuration is unchanged by the downgrade.
        await seed(pg_engine)
        case = await accepted_case(pg_engine)
        async with pg_engine.begin() as conn:

            def stage3(sync: sa.Connection) -> None:
                config = Config("alembic.ini")
                config.attributes["connection"] = sync
                command.downgrade(config, "0001_lean_persistence")

            await conn.run_sync(stage3)
        legacy = insight_for(case)
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.insights.insert().values(
                    **{**asdict(legacy), "record_provenance": json_value(legacy.record_provenance)}
                )
            )

            def upgrade(sync: sa.Connection) -> None:
                config = Config("alembic.ini")
                config.attributes["connection"] = sync
                command.upgrade(config, "head")
                command.check(config)

            await conn.run_sync(upgrade)
        detail = await reads.insight_detail(pg_engine, legacy.insight_id)
        assert detail.insight == legacy and detail.publication_status == "draft"
        assert detail.published_at is None and detail.publication_digest is None
        with pytest.raises(ValueError, match="published"):
            await reads.output_insights(pg_engine, (legacy.insight_id,))

    run(scenario())
