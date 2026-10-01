from collections.abc import Callable
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid7

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from research_atlas.application.document_acquisition import acquire_source_document
from research_atlas.application.ports.literature_source import LiteratureBatch
from research_atlas.domain.execution import ScreeningDecision, SearchExecution
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import SourceProvenance
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.discovery import DiscoveryPersistence
from research_atlas.infrastructure.persistence.evidence import (
    DocumentAcquisitionPersistence,
    ImmutableRecordConflict,
    apply_screening_decision,
    load_source_document,
    record_source_document,
)
from research_atlas.infrastructure.persistence.reads import run_sources
from research_atlas.infrastructure.persistence.runs import start_search_execution
from research_atlas.infrastructure.providers.openalex_content import (
    MAX_XML_BYTES,
    OpenAlexDocumentAcquirer,
)

from .conftest import run
from .helpers import NOW, count, observation, seed, source

XML = b'<?xml version="1.0"?><TEI><text>Exact retained bytes.</text></TEI>'
KEY = "test-only-credential"


async def persisted_openalex(engine: AsyncEngine, *extra_searches: str) -> UUID:
    await seed(engine, "search", *extra_searches)
    committed = await DiscoveryPersistence(engine).commit_discovery_batch(
        "search", None, LiteratureBatch((observation("W123"),), None, True)
    )
    assert committed.source_ids[0] is not None
    return committed.source_ids[0]


async def state(engine: AsyncEngine, source_id: UUID) -> str:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.select(s.run_sources.c.processing_state).where(
                    s.run_sources.c.run_id == "run", s.run_sources.c.source_id == source_id
                )
            )
        ).scalar_one()


async def acquire(
    engine: AsyncEngine,
    source_id: UUID,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    run_id: str = "run",
) -> UUID:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await acquire_source_document(
            DocumentAcquisitionPersistence(engine),
            run_id,
            source_id,
            OpenAlexDocumentAcquirer(KEY, client),
        )


def test_real_adapter_persists_exact_bytes_and_durable_identity_outside_transaction(
    pg_engine: AsyncEngine,
) -> None:
    checked_out = 0

    @event.listens_for(pg_engine.sync_engine, "checkout")
    def checkout(_connection: object, _record: object, _proxy: object) -> None:
        nonlocal checked_out
        checked_out += 1

    @event.listens_for(pg_engine.sync_engine, "checkin")
    def checkin(_connection: object, _record: object) -> None:
        nonlocal checked_out
        checked_out -= 1

    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)
        await start_search_execution(
            pg_engine,
            SearchExecution(
                "display",
                "run",
                "crossref",
                "crossref.search",
                "alternate metadata",
                (),
                1,
                NOW,
                None,
                "running",
            ),
        )
        alternate = observation(title="Alternate display title")
        alternate = replace(
            alternate,
            source=replace(
                alternate.source,
                provider_provenance=(SourceProvenance("crossref", "10.1/a", NOW),),
                source_url="https://publisher.test/alternate-display",
            ),
        )
        # Persist a NEW immutable snapshot. Its shared DOI resolves to the same Source;
        # its Crossref provider key does not introduce another OpenAlex acquisition ID.
        committed = await DiscoveryPersistence(pg_engine).commit_discovery_batch(
            "display", None, LiteratureBatch((alternate,), None, True)
        )
        assert committed.source_ids == (source_id,)
        assert await count(pg_engine, s.source_metadata_observations) == 2
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.sources.update()
                .where(s.sources.c.source_id == source_id)
                .values(display_observation_id=committed.observation_ids[0])
            )
            assert set(
                (
                    await conn.execute(
                        sa.select(s.source_identifiers.c.value).where(
                            s.source_identifiers.c.source_id == source_id,
                            s.source_identifiers.c.namespace == "openalex",
                        )
                    )
                ).scalars()
            ) == {"W123"}
        displayed = (await run_sources(pg_engine, "run"))[0].source
        assert displayed.source_id == source_id
        assert displayed.observation_id == committed.observation_ids[0]
        assert displayed.title == alternate.source.title
        assert displayed.source_url == alternate.source.source_url
        assert all(identifier.namespace != "openalex" for identifier in displayed.identifiers)

        def handler(request: httpx.Request) -> httpx.Response:
            assert checked_out == 0
            assert request.url.path == "/works/W123.grobid-xml"
            assert request.headers["Authorization"] == f"Bearer {KEY}"
            return httpx.Response(200, content=XML)

        document_id = await acquire(pg_engine, source_id, handler)
        doc, content = await load_source_document(pg_engine, document_id)
        assert content == XML and doc.content_sha256 == sha256(XML).hexdigest()
        assert doc.source_id == source_id and doc.status == "usable"
        assert doc.content_kind == "grobid_xml" and doc.media_type == "application/xml"
        assert doc.source_url == "https://content.openalex.org/works/W123.grobid-xml"
        assert KEY not in repr(doc) and doc.retrieved_at.tzinfo is not None
        assert await state(pg_engine, source_id) == "retrieved"
        assert await acquire(pg_engine, source_id, handler) == document_id
        assert await count(pg_engine, s.source_documents) == 1
        with pytest.raises(ImmutableRecordConflict):
            await record_source_document(
                pg_engine, replace(doc, retrieval_context="overwrite"), XML
            )
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(
                    s.source_documents.update().values(retrieval_context="overwrite")
                )

    run(scenario())


@pytest.mark.parametrize(
    "fault",
    [
        "missing_run",
        "missing_source",
        "zero",
        "malformed",
        "ambiguous_provider",
        "ambiguous_external",
        "contradictory_kinds",
    ],
)
def test_membership_and_conservative_durable_identity_fail_before_network(
    pg_engine: AsyncEngine,
    fault: str,
) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)
        run_id = "other" if fault == "missing_run" else "run"
        if fault == "missing_source":
            source_id = uuid7()
        async with pg_engine.begin() as conn:
            if fault in {"zero", "malformed", "ambiguous_external"}:
                await conn.execute(s.source_identifiers.delete())
            if fault == "malformed":
                await conn.execute(
                    s.source_identifiers.insert().values(
                        source_id=source_id,
                        kind="provider_record",
                        namespace="openalex",
                        value="A123",
                    )
                )
            if fault in {"ambiguous_provider", "ambiguous_external", "contradictory_kinds"}:
                kind = "provider_record" if fault == "ambiguous_provider" else "external_identifier"
                await conn.execute(
                    s.source_identifiers.insert().values(
                        source_id=source_id, kind=kind, namespace="openalex", value="W456"
                    )
                )
                if fault == "ambiguous_external":
                    await conn.execute(
                        s.source_identifiers.insert().values(
                            source_id=source_id, kind=kind, namespace="openalex", value="W789"
                        )
                    )

        def handler(_request: httpx.Request) -> httpx.Response:
            raise AssertionError("identity or membership failure must precede network access")

        expected = (
            "membership"
            if fault.startswith("missing")
            else "ambiguous"
            if "ambiguous" in fault or fault == "contradictory_kinds"
            else "no usable"
        )
        with pytest.raises(ValueError, match=expected):
            await acquire(pg_engine, source_id, handler, run_id=run_id)
        assert await count(pg_engine, s.source_documents) == 0

    run(scenario())


@pytest.mark.parametrize("provider_record", [False, True])
def test_equivalent_authoritative_ids_and_external_fallback(
    pg_engine: AsyncEngine,
    provider_record: bool,
) -> None:
    async def scenario() -> None:
        await seed(pg_engine)
        source_id = await source(pg_engine)
        async with pg_engine.begin() as conn:
            await conn.execute(
                s.source_identifiers.insert().values(
                    source_id=source_id,
                    kind="external_identifier",
                    namespace="openalex",
                    value="W123",
                )
            )
            if provider_record:
                await conn.execute(
                    s.source_identifiers.insert().values(
                        source_id=source_id,
                        kind="provider_record",
                        namespace="openalex",
                        value="https://openalex.org/W123",
                    )
                )
        assert (
            await DocumentAcquisitionPersistence(pg_engine).load_acquisition_identity(
                "run", source_id, "openalex"
            )
            == "W123"
        )

    run(scenario())


@pytest.mark.parametrize("outcome", ["unavailable", "failed", "incomplete"])
def test_nonusable_attempts_and_later_success(pg_engine: AsyncEngine, outcome: str) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)

        def handler(_request: httpx.Request) -> httpx.Response:
            if outcome == "incomplete":
                return httpx.Response(
                    200, content=XML, headers={"Content-Length": str(MAX_XML_BYTES + 1)}
                )
            return httpx.Response(
                404 if outcome == "unavailable" else 401, content=b"remote secret"
            )

        first = await acquire(pg_engine, source_id, handler)
        doc, content = await load_source_document(pg_engine, first)
        assert doc.status == outcome and content is None and doc.content_sha256 is None
        assert KEY not in repr(doc) and "remote secret" not in repr(doc)
        assert await state(pg_engine, source_id) == (
            "unavailable" if outcome == "unavailable" else "failed"
        )
        second = await acquire(pg_engine, source_id, handler)
        assert second != first and await count(pg_engine, s.source_documents) == 2
        await acquire(pg_engine, source_id, lambda _request: httpx.Response(200, content=XML))
        assert await state(pg_engine, source_id) == "retrieved"
        assert await count(pg_engine, s.source_documents) == 3

    run(scenario())


def test_commit_failure_rolls_back_document_and_state(pg_engine: AsyncEngine) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)
        async with pg_engine.begin() as conn:
            # Existing per-test schema only. Inject a DB failure AFTER the document insert.
            await conn.execute(
                sa.text(
                    "CREATE FUNCTION reject_acquisition_state() RETURNS trigger "
                    "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test state write failure' "
                    "USING ERRCODE = '23514'; END $$"
                )
            )
            await conn.execute(
                sa.text(
                    "CREATE TRIGGER reject_acquisition_state BEFORE UPDATE ON run_sources "
                    "FOR EACH ROW EXECUTE FUNCTION reject_acquisition_state()"
                )
            )
        with pytest.raises(IntegrityError):
            await acquire(pg_engine, source_id, lambda _request: httpx.Response(200, content=XML))
        assert await count(pg_engine, s.source_documents) == 0
        assert await state(pg_engine, source_id) == "discovered"

    run(scenario())


@pytest.mark.parametrize("exclude_during_request", [False, True])
def test_exclusion_is_checked_before_acquisition_and_again_before_commit(
    pg_engine: AsyncEngine,
    exclude_during_request: bool,
) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)
        decision = ScreeningDecision(
            "exclude", "run", source_id, "exclude", RecordProvenance("run", NOW, "manual")
        )
        if not exclude_during_request:
            await apply_screening_decision(pg_engine, decision)

        async def handler(_request: httpx.Request) -> httpx.Response:
            assert exclude_during_request
            await apply_screening_decision(pg_engine, decision)
            return httpx.Response(200, content=XML)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="excluded"):
                await acquire_source_document(
                    DocumentAcquisitionPersistence(pg_engine),
                    "run",
                    source_id,
                    OpenAlexDocumentAcquirer(KEY, client),
                )
        assert await count(pg_engine, s.source_documents) == 0
        assert await state(pg_engine, source_id) == "excluded"

    run(scenario())


def test_discovery_during_retrieval_makes_identity_ambiguous_and_commit_rejects(
    pg_engine: AsyncEngine,
) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine, "concurrent")
        initial_state = await state(pg_engine, source_id)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url.path == "/works/W123.grobid-xml"
            # The actual application has loaded W123 and closed its DB read.
            # A separate discovery transaction now reconciles W456 by the same DOI,
            # locking the existing Source before promoting its new provider key.
            committed = await DiscoveryPersistence(pg_engine).commit_discovery_batch(
                "concurrent", None, LiteratureBatch((observation("W456"),), None, True)
            )
            assert committed.source_ids == (source_id,)
            return httpx.Response(200, content=XML)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="ambiguous"):
                await acquire_source_document(
                    DocumentAcquisitionPersistence(pg_engine),
                    "run",
                    source_id,
                    OpenAlexDocumentAcquirer(KEY, client),
                )
        assert calls == 1
        assert await count(pg_engine, s.source_documents) == 0
        assert await state(pg_engine, source_id) == initial_state

    run(scenario())


@pytest.mark.parametrize("change", ["missing", "different"])
def test_missing_or_changed_identity_at_commit_leaves_document_and_state_unchanged(
    pg_engine: AsyncEngine,
    change: str,
) -> None:
    async def scenario() -> None:
        source_id = await persisted_openalex(pg_engine)
        initial_state = await state(pg_engine, source_id)

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/works/W123.grobid-xml"
            async with pg_engine.begin() as conn:
                await conn.execute(
                    sa.select(s.sources.c.source_id)
                    .where(s.sources.c.source_id == source_id)
                    .with_for_update()
                )
                condition = (
                    s.source_identifiers.c.source_id == source_id,
                    s.source_identifiers.c.namespace == "openalex",
                )
                if change == "missing":
                    await conn.execute(s.source_identifiers.delete().where(*condition))
                else:
                    await conn.execute(
                        s.source_identifiers.update().where(*condition).values(value="W456")
                    )
            return httpx.Response(200, content=XML)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="no usable" if change == "missing" else "changed"):
                await acquire_source_document(
                    DocumentAcquisitionPersistence(pg_engine),
                    "run",
                    source_id,
                    OpenAlexDocumentAcquirer(KEY, client),
                )
        assert await count(pg_engine, s.source_documents) == 0
        assert await state(pg_engine, source_id) == initial_state

    run(scenario())
