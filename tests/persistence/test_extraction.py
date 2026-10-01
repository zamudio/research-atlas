from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from uuid import uuid7

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.extraction import extract_source_document
from research_atlas.application.grobid_text import prepare_grobid_text
from research_atlas.application.ports.extraction import StructuredExtractionResult
from research_atlas.domain.content import EvidenceAnchor, Extraction
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.execution import ScreeningDecision
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import StudyRecord
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.evidence import (
    ImmutableRecordConflict,
    apply_screening_decision,
    load_source_document,
    publish_accepted_extraction,
    record_extraction,
    record_source_document,
)
from research_atlas.infrastructure.persistence.extraction import PostgresExtractionPersistence
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from tests.unit.test_extraction import PASSAGE, XML, FakeProvider, proposal_bytes

from .conftest import run
from .helpers import CONFIGURATION, NOW, count, document, evidence, seed, source


def test_real_execution_derivation_raw_publication_selection_and_no_open_connection(
    pg_engine: AsyncEngine,
) -> None:
    checked_out: set[int] = set()

    def checkout(dbapi: object, record: object, proxy: object) -> None:
        checked_out.add(id(record))

    def checkin(dbapi: object, record: object) -> None:
        checked_out.discard(id(record))

    event.listen(pg_engine.sync_engine, "checkout", checkout)
    event.listen(pg_engine.sync_engine, "checkin", checkin)

    class Provider(FakeProvider):
        async def extract(
            self, instructions: str, document_text: str, schema: Mapping[str, object]
        ) -> StructuredExtractionResult:
            assert not checked_out  # not even a pooled connection survives into model I/O
            return await super().extract(instructions, document_text, schema)

    async def scenario() -> None:
        await seed(pg_engine)
        parent = replace(document(await source(pg_engine), XML), content_kind="grobid_xml")
        await record_source_document(pg_engine, parent, XML)
        projection, content = prepare_grobid_text(parent, XML)
        first_id = await record_source_document(pg_engine, projection, content)
        assert (
            await record_source_document(
                pg_engine, replace(projection, document_id=uuid7()), content
            )
            == first_id
        )
        provider = Provider()
        result = await extract_source_document(
            PostgresExtractionPersistence(pg_engine),
            provider,
            run_id="run",
            source_id=parent.source_id,
            document_id=parent.document_id,
        )
        assert result.status == "accepted" and result.source_document_id == first_id
        assert await count(pg_engine, s.source_documents) == 2
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 1
        assert await load_source_document(pg_engine, parent.document_id) == (parent, XML)
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.extractions))).mappings().one()
            assert row["raw_output"] == provider.raw
            assert row["raw_output_sha256"] == sha256(provider.raw).hexdigest()
            assert row["configuration_sha256"] == sha256(row["configuration"]).hexdigest()
            membership = (await conn.execute(sa.select(s.run_sources))).mappings().one()
            assert membership["selected_extraction_id"] == result.extraction_id
            assert membership["processing_state"] == "extracted"
            anchors = (await conn.execute(sa.select(s.findings.c.anchors))).scalar_one()
            assert anchors[0]["passage"] == PASSAGE and PASSAGE.encode() in content
            tables = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = current_schema() "
                        "AND table_type = 'BASE TABLE' AND table_name != 'alembic_version'"
                    )
                )
            ).scalar_one()
            assert tables == 14
            await conn.run_sync(lambda connection: _check_migrations(connection))
        for values in ({"raw_output": b"changed"}, {"raw_output_sha256": "0" * 64}):
            with pytest.raises(IntegrityError):
                async with pg_engine.begin() as conn:
                    await conn.execute(s.extractions.update().values(**values))
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(s.extractions.delete())

    run(scenario())


def test_legacy_accepted_extraction_keeps_retry_identity_after_raw_migration(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        content = b"The measured outcome did not change. Results remain uncertain."
        await record_source_document(pg_engine, doc, content)
        extraction, study, finding = evidence(doc)
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        async with pg_engine.begin() as conn:
            before = (
                await conn.execute(sa.select(s.extractions.c.publication_digest))
            ).scalar_one()

            def round_trip(connection: sa.Connection) -> None:
                config = Config("alembic.ini")
                config.attributes["connection"] = connection
                command.downgrade(config, "0002_insight_publication")
                assert "raw_output" not in {
                    column["name"] for column in sa.inspect(connection).get_columns("extractions")
                }
                command.upgrade(config, "head")
                command.check(config)

            await conn.run_sync(round_trip)
            row = (await conn.execute(sa.select(s.extractions))).mappings().one()
            assert row["raw_output"] is None and row["raw_output_sha256"] is None
            assert row["publication_digest"] == before
        await publish_accepted_extraction(
            pg_engine, extraction, CONFIGURATION, (study,), (finding,)
        )
        assert await count(pg_engine, s.extractions) == 1

    run(scenario())


def _check_migrations(connection: sa.Connection) -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.check(config)


@pytest.mark.parametrize(
    "raw,status",
    [
        (b"bad JSON", "failed"),
        (b"{}", "failed"),
        (b'{"studies": []}', "review_needed"),
        (proposal_bytes("fabricated passage"), "review_needed"),
    ],
)
def test_unpublishable_returned_output_is_retained_without_normalized_evidence(
    pg_engine: AsyncEngine,
    raw: bytes,
    status: str,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        parent = replace(document(await source(pg_engine), XML), content_kind="grobid_xml")
        await record_source_document(pg_engine, parent, XML)
        result = await extract_source_document(
            PostgresExtractionPersistence(pg_engine),
            FakeProvider(raw),
            run_id="run",
            source_id=parent.source_id,
            document_id=parent.document_id,
        )
        assert result.status == status
        assert result.validation_outcome == "failed" and result.review_outcome == "pending"
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 0
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.extractions))).mappings().one()
            assert row["raw_output"] == raw and row["raw_output_sha256"] == sha256(raw).hexdigest()
            assert row["status"] == status
            assert row["validation_outcome"] == "failed" and row["review_outcome"] == "pending"
            assert (
                await conn.execute(sa.select(s.run_sources.c.selected_extraction_id))
            ).scalar_one() is None

    run(scenario())


@pytest.mark.parametrize("eligibility_change", ["exclude", "remove_membership"])
def test_provider_failure_no_raw_and_eligibility_change_during_io_rolls_back(
    pg_engine: AsyncEngine,
    eligibility_change: str,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        parent = replace(document(await source(pg_engine), XML), content_kind="grobid_xml")
        await record_source_document(pg_engine, parent, XML)
        store = PostgresExtractionPersistence(pg_engine)
        provider = FakeProvider()
        provider.failure = True
        failed = await extract_source_document(
            store,
            provider,
            run_id="run",
            source_id=parent.source_id,
            document_id=parent.document_id,
        )
        assert failed.status == "failed"
        assert failed.validation_outcome == "pending" and failed.review_outcome == "pending"
        async with pg_engine.connect() as conn:
            assert (await conn.execute(sa.select(s.extractions.c.raw_output))).scalar_one() is None
            assert (
                await conn.execute(sa.select(s.extractions.c.validation_outcome))
            ).scalar_one() == "pending"

        class IneligibleProvider(FakeProvider):
            async def extract(
                self, instructions: str, document_text: str, schema: Mapping[str, object]
            ) -> StructuredExtractionResult:
                if eligibility_change == "exclude":
                    await apply_screening_decision(
                        pg_engine,
                        ScreeningDecision(
                            decision_id="exclude",
                            run_id="run",
                            source_id=parent.source_id,
                            decision="exclude",
                            record_provenance=RecordProvenance("run", NOW, "test"),
                            rationale="eligibility changed",
                        ),
                    )
                else:
                    async with pg_engine.begin() as conn:
                        await conn.execute(s.run_sources.delete())
                return await super().extract(instructions, document_text, schema)

        result = await extract_source_document(
            store,
            IneligibleProvider(),
            run_id="run",
            source_id=parent.source_id,
            document_id=parent.document_id,
        )
        assert result.status == "review_needed"
        assert result.validation_outcome == "passed" and result.review_outcome == "pending"
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 0
        async with pg_engine.connect() as conn:
            extraction_row = (
                (
                    await conn.execute(
                        sa.select(s.extractions).where(
                            s.extractions.c.extraction_id == result.extraction_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert extraction_row["validation_outcome"] == "passed"
            assert extraction_row["review_outcome"] == "pending"
            assert extraction_row["raw_output"] == proposal_bytes()
            row = (await conn.execute(sa.select(s.run_sources))).mappings().one_or_none()
            if eligibility_change == "exclude":
                assert row is not None
                assert (
                    row["processing_state"] == "excluded" and row["selected_extraction_id"] is None
                )
            else:
                assert row is None
        with pytest.raises(ValueError):
            await extract_source_document(
                store,
                FakeProvider(),
                run_id="run",
                source_id=parent.source_id,
                document_id=parent.document_id,
            )

    run(scenario())


@pytest.mark.parametrize(
    "completion",
    [
        {"done": False},
        {"done": True, "done_reason": "length"},
    ],
)
def test_incomplete_ollama_generation_is_failed_pending_with_exact_raw_output(
    pg_engine: AsyncEngine,
    completion: dict[str, object],
) -> None:
    raw = b" \n" + proposal_bytes() + b"\n "
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen3.5:4b",
                "message": {"content": raw.decode(), "thinking": "discard"},
                **completion,
            },
        )

    async def scenario() -> None:
        await seed(pg_engine)
        parent = replace(document(await source(pg_engine), XML), content_kind="grobid_xml")
        await record_source_document(pg_engine, parent, XML)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await extract_source_document(
                PostgresExtractionPersistence(pg_engine),
                OllamaExtractor(ProviderSettings(extraction_model="qwen3.5:4b"), client),
                run_id="run",
                source_id=parent.source_id,
                document_id=parent.document_id,
            )
        assert result.status == "failed" and result.validation_outcome == "pending"
        assert result.review_outcome == "pending"
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.extractions))).mappings().one()
            assert row["status"] == "failed" and row["validation_outcome"] == "pending"
            assert row["raw_output"] == raw and row["raw_output_sha256"] == sha256(raw).hexdigest()
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 0

    run(scenario())
    assert calls == 1


def test_unexpected_publication_invariant_propagates_and_rolls_back(pg_engine: AsyncEngine) -> None:
    class CorruptingPublication(PostgresExtractionPersistence):
        async def publish(
            self,
            extraction: Extraction,
            configuration: bytes,
            raw_output: bytes,
            studies: tuple[StudyRecord, ...],
            findings: tuple[FindingRecord, ...],
        ) -> None:
            invalid = replace(findings[0], evidence_anchors=(EvidenceAnchor("nonexistent"),))
            await super().publish(extraction, configuration, raw_output, studies, (invalid,))

    async def scenario() -> None:
        await seed(pg_engine)
        parent = replace(document(await source(pg_engine), XML), content_kind="grobid_xml")
        await record_source_document(pg_engine, parent, XML)
        provider = FakeProvider()
        with pytest.raises(ValueError, match="exact passages"):
            await extract_source_document(
                CorruptingPublication(pg_engine),
                provider,
                run_id="run",
                source_id=parent.source_id,
                document_id=parent.document_id,
            )
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 0
        async with pg_engine.connect() as conn:
            row = (await conn.execute(sa.select(s.extractions))).mappings().one()
            assert row["status"] == "running" and row["raw_output"] == provider.raw
            assert (
                await conn.execute(sa.select(s.run_sources.c.selected_extraction_id))
            ).scalar_one() is None

    run(scenario())


def test_raw_checksum_sql_checks_publication_rollback_and_raw_identity(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        doc = document(await source(pg_engine))
        await record_source_document(
            pg_engine, doc, b"The measured outcome did not change. Results remain uncertain."
        )
        extraction, study, finding = evidence(doc)
        pending = replace(
            extraction,
            status="running",
            completed_at=None,
            validation_outcome="pending",
            review_outcome="pending",
        )
        await record_extraction(pg_engine, pending, CONFIGURATION, raw_output=b"initial")
        for values in (
            {"raw_output": None},
            {"raw_output_sha256": None},
            {"raw_output_sha256": "0" * 64},
        ):
            with pytest.raises(IntegrityError):
                async with pg_engine.begin() as conn:
                    await conn.execute(s.extractions.update().values(**values))
        invalid = replace(
            finding, finding_id=uuid7(), evidence_anchors=(EvidenceAnchor("invented"),)
        )
        with pytest.raises(ValueError):
            await publish_accepted_extraction(
                pg_engine,
                extraction,
                CONFIGURATION,
                (study,),
                (finding, invalid),
                raw_output=b"exact response",
                select_for_run=True,
            )
        assert await count(pg_engine, s.studies) == await count(pg_engine, s.findings) == 0
        async with pg_engine.connect() as conn:
            assert (await conn.execute(sa.select(s.extractions.c.status))).scalar_one() == "running"
            assert (
                await conn.execute(sa.select(s.extractions.c.raw_output))
            ).scalar_one() == b"initial"
            assert (
                await conn.execute(sa.select(s.run_sources.c.selected_extraction_id))
            ).scalar_one() is None
        await publish_accepted_extraction(
            pg_engine,
            extraction,
            CONFIGURATION,
            (study,),
            (finding,),
            raw_output=b"exact response",
            select_for_run=True,
        )
        await publish_accepted_extraction(
            pg_engine,
            extraction,
            CONFIGURATION,
            (study,),
            (finding,),
            raw_output=b"exact response",
        )
        with pytest.raises(ImmutableRecordConflict):
            await publish_accepted_extraction(
                pg_engine,
                extraction,
                CONFIGURATION,
                (study,),
                (finding,),
                raw_output=b"changed JSON spacing",
            )
        assert await count(pg_engine, s.extractions) == 1

    run(scenario())
