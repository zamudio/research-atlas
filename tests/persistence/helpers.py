from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid7

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.ports.literature_source import LiteratureRecord
from research_atlas.domain.content import EvidenceAnchor, Extraction, SourceDocument
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.execution import SearchExecution
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import (
    ExternalIdentifier,
    ResearchRun,
    SourceProvenance,
    SourceRecord,
    StudyRecord,
)
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.runs import (
    create_project,
    create_research_run,
    start_search_execution,
)
from research_atlas.schemas.project_profile import ProjectProfile

NOW = datetime(2026, 9, 29, tzinfo=UTC)
CONTENT = b"The measured outcome did not change. Results remain uncertain."
CONFIGURATION = b"Extract reported findings with exact evidence passages."


def observation(
    publication: str | None = "W1",
    doi: str | None = "10.1/a",
    *,
    title: str = "Reported title",
    extra: tuple[ExternalIdentifier, ...] = (),
) -> LiteratureRecord:
    credits = (BibliographicCredit("Alice"), BibliographicCredit("Bob"))
    return LiteratureRecord(
        SourceRecord(
            uuid7(),
            title,
            ("Alice", "Bob"),
            2026,
            "article",
            (SourceProvenance("openalex", publication, NOW),),
            ((ExternalIdentifier("doi", doi),) if doi else ()) + extra,
        ),
        credits,
    )


async def seed(engine: AsyncEngine, *search_ids: str) -> None:
    await create_project(engine, ProjectProfile(project_id="project", display_name="Test"))
    await create_research_run(
        engine, ResearchRun("run", "project", "Original request", "running", NOW, started_at=NOW)
    )
    for search_id in search_ids:
        await start_search_execution(
            engine,
            SearchExecution(
                search_id,
                "run",
                "openalex",
                "openalex.search",
                "query",
                (),
                10,
                NOW,
                None,
                "running",
            ),
        )


async def count(engine: AsyncEngine, table: sa.Table) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


def document(source_id: UUID, content: bytes = CONTENT) -> SourceDocument:
    return SourceDocument(
        uuid7(),
        source_id,
        "full_text",
        "caller supplied UTF-8",
        NOW,
        "usable",
        sha256(content).hexdigest(),
        media_type="text/plain; charset=utf-8",
    )


def evidence(doc: SourceDocument) -> tuple[Extraction, StudyRecord, FindingRecord]:
    provenance = RecordProvenance("run", NOW, "manual")
    extraction = Extraction(
        uuid7(),
        "run",
        doc.document_id,
        "reported findings",
        sha256(CONFIGURATION).hexdigest(),
        provenance,
        "accepted",
        "passed",
        "not_required",
        NOW,
        NOW,
    )
    study = StudyRecord(
        uuid7(),
        doc.source_id,
        extraction.extraction_id,
        "experiment",
        "adults",
        "learning",
        "lab",
        "40",
        provenance,
    )
    finding = FindingRecord(
        uuid7(),
        study.study_id,
        "change?",
        "measured outcome",
        "No change",
        "null",
        "reported",
        provenance,
        (EvidenceAnchor("The measured outcome did not change."),),
        uncertainty="uncertain",
    )
    return extraction, study, finding


async def source(engine: AsyncEngine) -> UUID:
    value = uuid7()
    async with engine.begin() as conn:
        await conn.execute(s.sources.insert().values(source_id=value))
        await conn.execute(s.run_sources.insert().values(run_id="run", source_id=value))
    return value
