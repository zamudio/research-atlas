from dataclasses import replace
from uuid import uuid7

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.domain.content import EvidenceAnchor
from research_atlas.domain.execution import ScreeningDecision
from research_atlas.domain.studies import ResearchRun
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.evidence import (
    ImmutableRecordConflict,
    apply_screening_decision,
    load_source_document,
    publish_accepted_extraction,
    record_extraction,
    record_source_document,
    select_run_source_extraction,
    set_processing_state,
)
from research_atlas.infrastructure.persistence.runs import create_research_run

from .conftest import run
from .helpers import CONFIGURATION, CONTENT, NOW, count, document, evidence, seed, source


def test_document_checksum_replay_version_and_exact_read(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        source_id = await source(pg_engine)
        doc = document(source_id)
        with pytest.raises(ValueError, match="checksum"):
            await record_source_document(pg_engine, doc, b"wrong")
        with pytest.raises(ValueError, match="retained"):
            await record_source_document(pg_engine, doc, None)
        assert await record_source_document(pg_engine, doc, CONTENT) == doc.document_id
        assert (
            await record_source_document(pg_engine, replace(doc, document_id=uuid7()), CONTENT)
            == doc.document_id
        )
        assert await load_source_document(pg_engine, doc.document_id) == (doc, CONTENT)
        changed = document(source_id, b"new representation")
        await record_source_document(pg_engine, changed, b"new representation")
        assert await count(pg_engine, s.source_documents) == 2
        with pytest.raises(ImmutableRecordConflict):
            await record_source_document(
                pg_engine, replace(changed, document_id=doc.document_id), b"new representation"
            )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.source_documents.update()
                    .where(s.source_documents.c.document_id == doc.document_id)
                    .values(content=b"overwrite")
                )

    run(scenario())


def test_database_rejects_wrong_checksum_even_without_operation(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.source_documents.insert().values(
                        document_id=doc.document_id,
                        source_id=doc.source_id,
                        content_kind=doc.content_kind,
                        retrieval_context="supplied",
                        retrieved_at=NOW,
                        status="usable",
                        content=b"wrong",
                        content_sha256=doc.content_sha256,
                    )
                )

    run(scenario())


@pytest.mark.parametrize(
    "fault", ["source", "extraction", "passage", "locator_only", "finding_study", "configuration"]
)
def test_invalid_publication_rolls_back_extraction_studies_and_all_findings(
    pg_engine: AsyncEngine, fault: str
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(pg_engine, doc, CONTENT)
        extraction, study, first = evidence(doc)
        invalid = replace(first, finding_id=uuid7())
        configuration = CONFIGURATION
        if fault == "source":
            study = replace(study, source_id=uuid7())
        elif fault == "extraction":
            study = replace(study, extraction_id=uuid7())
        elif fault == "passage":
            invalid = replace(
                invalid, evidence_anchors=(EvidenceAnchor("Passage from another document"),)
            )
        elif fault == "locator_only":
            invalid = replace(invalid, evidence_anchors=(EvidenceAnchor(locator="page 1"),))
        elif fault == "finding_study":
            invalid = replace(invalid, source_study_id=uuid7())
        else:
            configuration = b"different instructions"
        with pytest.raises(ValueError):
            await publish_accepted_extraction(
                pg_engine, extraction, configuration, (study,), (first, invalid)
            )
        assert await count(pg_engine, s.extractions) == 0
        assert await count(pg_engine, s.studies) == 0
        assert await count(pg_engine, s.findings) == 0

    run(scenario())


def test_reextraction_selection_replay_and_cross_run_reuse_keep_old_evidence(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(pg_engine, doc, CONTENT)
        first, first_study, first_finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, first, CONFIGURATION, (first_study,), (first_finding,)
        )
        await publish_accepted_extraction(
            pg_engine, first, CONFIGURATION, (first_study,), (first_finding,)
        )
        with pytest.raises(ImmutableRecordConflict):
            await publish_accepted_extraction(
                pg_engine,
                first,
                CONFIGURATION,
                (first_study,),
                (replace(first_finding, result_summary="changed"),),
            )
        await select_run_source_extraction(pg_engine, "run", doc.source_id, first.extraction_id)
        second, second_study, second_finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, second, CONFIGURATION, (second_study,), (second_finding,)
        )
        await select_run_source_extraction(pg_engine, "run", doc.source_id, second.extraction_id)
        async with pg_engine.connect() as conn:
            assert (
                await conn.execute(sa.select(s.run_sources.c.processing_state))
            ).scalar_one() == "discovered"
        await set_processing_state(pg_engine, "run", doc.source_id, "extracted")
        await set_processing_state(pg_engine, "run", doc.source_id, "failed")
        async with pg_engine.connect() as conn:
            assert (
                await conn.execute(sa.select(s.run_sources.c.selected_extraction_id))
            ).scalar_one() == second.extraction_id
        await create_research_run(
            pg_engine, ResearchRun("another", "project", "Reuse evidence", "queued", NOW)
        )
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.run_sources.insert().values(run_id="another", source_id=doc.source_id)
            )
        await select_run_source_extraction(pg_engine, "another", doc.source_id, first.extraction_id)
        assert await count(pg_engine, s.extractions) == 2
        assert await count(pg_engine, s.studies) == 2
        assert await count(pg_engine, s.findings) == 2

    run(scenario())


def test_selection_rejects_failed_missing_and_wrong_source(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        other_source = await source(pg_engine)
        await record_source_document(pg_engine, doc, CONTENT)
        extraction, study, finding = evidence(doc)
        failed = replace(
            extraction,
            extraction_id=uuid7(),
            status="failed",
            validation_outcome="failed",
            review_outcome="pending",
        )
        await record_extraction(pg_engine, failed, CONFIGURATION)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        for source_id, extraction_id in (
            (doc.source_id, failed.extraction_id),
            (doc.source_id, uuid7()),
            (other_source, extraction.extraction_id),
        ):
            with pytest.raises(ValueError, match="selection"):
                await select_run_source_extraction(pg_engine, "run", source_id, extraction_id)

    run(scenario())


def test_pending_attempt_can_publish_but_finalized_attempt_cannot_be_overwritten(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(pg_engine, doc, CONTENT)
        extraction, study, finding = evidence(doc)
        pending = replace(
            extraction,
            status="running",
            completed_at=None,
            validation_outcome="pending",
            review_outcome="pending",
        )
        await record_extraction(pg_engine, pending, CONFIGURATION)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        with pytest.raises(ImmutableRecordConflict):
            await record_extraction(pg_engine, pending, CONFIGURATION)
        assert await count(pg_engine, s.extractions) == 1

    run(scenario())


def test_screening_is_current_membership_data_and_exclusion_is_atomic(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(pg_engine, doc, CONTENT)
        extraction, study, finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        scoped = ScreeningDecision(
            "study-screen",
            "run",
            doc.source_id,
            "exclude",
            study.record_provenance,
            ("scope",),
            study.study_id,
        )
        await apply_screening_decision(pg_engine, scoped)
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.run_sources))).mappings().one()
            assert row["screening_decision"] is None and row["processing_state"] == "discovered"
        await apply_screening_decision(
            pg_engine, replace(scoped, decision_id="source-screen", study_id=None)
        )
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.run_sources))).mappings().one()
            assert row["screening_decision"] == "exclude" and row["processing_state"] == "excluded"
            assert str(study.study_id) in row["scoped_screening"]
        with pytest.raises(IntegrityError):
            await set_processing_state(pg_engine, "run", doc.source_id, "retrieved")

    run(scenario())


def test_missing_parent_and_published_deletion_are_rejected(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(pg_engine, doc, CONTENT)
        extraction, study, finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.findings.insert().values(
                        finding_id=uuid7(), study_id=uuid7(), anchors=[{"passage": "text"}], data={}
                    )
                )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.insight_findings.insert().values(
                        insight_id=uuid7(),
                        finding_id=finding.finding_id,
                        relationship="contextual",
                        rationale="explicit",
                    )
                )
        insight_id = uuid7()
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.insights.insert().values(
                    insight_id=insight_id,
                    run_id="run",
                    claim="Schema integrity fixture",
                    configuration_sha256=extraction.configuration_sha256,
                    record_provenance={},
                    qualifications=[],
                    uncertainty_and_limitations=[],
                    generalizability_notes=[],
                )
            )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.insight_findings.insert().values(
                        insight_id=insight_id,
                        finding_id=uuid7(),
                        relationship="contextual",
                        rationale="explicit",
                    )
                )
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.insight_findings.insert().values(
                    insight_id=insight_id,
                    finding_id=finding.finding_id,
                    relationship="contextual",
                    rationale="explicit",
                )
            )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(s.insights.delete())
        for table in (
            s.projects,
            s.research_runs,
            s.sources,
            s.source_documents,
            s.extractions,
            s.studies,
            s.findings,
        ):
            with pytest.raises(IntegrityError):
                async with pg_engine.begin() as conn:
                    await conn.execute(table.delete())
        assert await count(pg_engine, s.findings) == 1

    run(scenario())
