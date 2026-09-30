from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.durable_ingestion import ingest_one_batch
from research_atlas.application.ports.literature_source import LiteratureBatch, LiteratureQuery
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.discovery import DiscoveryPersistence
from research_atlas.infrastructure.persistence.evidence import (
    publish_accepted_extraction,
    record_source_document,
    select_run_source_extraction,
    set_processing_state,
)

from .conftest import run
from .helpers import CONFIGURATION, CONTENT, document, evidence, observation, seed


def test_run_search_source_document_extraction_findings_survive_resume(
    pg_engine: AsyncEngine,
) -> None:
    class Provider:
        provider_id = "openalex"
        operation_id = "openalex.search"

        async def search(
            self, query: LiteratureQuery, *, checkpoint: str | None = None
        ) -> LiteratureBatch:
            assert query.query == "query" and query.limit == 10
            if checkpoint is None:
                return LiteratureBatch((observation(),), "resume", False)
            assert checkpoint == "resume"
            return LiteratureBatch((), None, True, 1)

    async def scenario() -> None:
        await seed(pg_engine, "search")
        first = await ingest_one_batch(DiscoveryPersistence(pg_engine), "search", Provider())
        assert first is not None and first.source_ids[0] is not None
        doc = document(first.source_ids[0])
        assert await record_source_document(pg_engine, doc, CONTENT) == doc.document_id
        extraction, study, finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        await select_run_source_extraction(
            pg_engine, "run", doc.source_id, extraction.extraction_id
        )
        await set_processing_state(pg_engine, "run", doc.source_id, "extracted")
        # A new persistence object resumes exclusively from PostgreSQL, not collector state.
        restarted = DiscoveryPersistence(pg_engine)
        final = await ingest_one_batch(restarted, "search", Provider())
        assert final is not None and final.exhausted
        assert (await restarted.load_search_resume_state("search")).completed_batches == 2
        async with pg_engine.connect() as conn:
            path = s.findings.join(s.studies).join(s.extractions).join(s.source_documents)
            row = (
                await conn.execute(
                    select(s.findings.c.finding_id, s.source_documents.c.content).select_from(path)
                )
            ).one()
            assert row.finding_id == finding.finding_id and row.content == CONTENT
            assert (
                await conn.execute(select(s.research_runs.c.request))
            ).scalar_one() == "Original request"
            assert (
                await conn.execute(select(s.run_sources.c.processing_state))
            ).scalar_one() == "extracted"

    run(scenario())
