"""Immutable documents, acquisition outcomes and supplied accepted evidence."""

from dataclasses import asdict
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from research_atlas.application.ports.extraction import ExtractionEligibilityChanged
from research_atlas.application.source_identity import ExactSourceKey, openalex_acquisition_identity
from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.execution import ScreeningDecision
from research_atlas.domain.studies import StudyRecord
from research_atlas.infrastructure.persistence import schema as s
from research_atlas.infrastructure.persistence.serialization import digest, json_value


class ImmutableRecordConflict(ValueError):
    """Retry identity was reused for different finalized content/evidence."""


def verify_content(content: bytes | None, checksum: str | None, *, usable: bool) -> None:
    if usable and content is None:
        raise ValueError("usable document requires retained anchorable content")
    if (content is None) != (checksum is None):
        raise ValueError("content and checksum must be supplied together")
    if content is not None and sha256(content).hexdigest() != checksum:
        raise ValueError("content checksum mismatch")


async def record_source_document(
    engine: AsyncEngine,
    document: SourceDocument,
    content: bytes | None,
) -> UUID:
    verify_content(content, document.content_sha256, usable=document.status == "usable")
    json_value(document)
    async with engine.begin() as conn:
        return await _record_source_document(conn, document, content)


async def _record_source_document(
    conn: AsyncConnection, document: SourceDocument, content: bytes | None
) -> UUID:
    verify_content(content, document.content_sha256, usable=document.status == "usable")
    json_value(document)
    values = {**asdict(document), "content": content}
    # Both UUID replay and usable-version uniqueness are backed by PostgreSQL.
    inserted = (
        await conn.execute(
            insert(s.source_documents)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(s.source_documents.c.document_id)
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted
    same_id = (
        (
            await conn.execute(
                sa.select(s.source_documents).where(
                    s.source_documents.c.document_id == document.document_id
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if same_id is not None:
        if any(same_id[key] != value for key, value in values.items()):
            raise ImmutableRecordConflict("document UUID already identifies a different record")
        return document.document_id
    if document.status != "usable":
        raise ImmutableRecordConflict("document retry conflict")
    return (
        await conn.execute(
            sa.select(s.source_documents.c.document_id).where(
                s.source_documents.c.source_id == document.source_id,
                s.source_documents.c.content_kind == document.content_kind,
                s.source_documents.c.content_sha256 == document.content_sha256,
                s.source_documents.c.status == "usable",
            )
        )
    ).scalar_one()


async def _acquisition_membership(
    conn: AsyncConnection, run_id: str, source_id: UUID, *, lock: bool = False
) -> None:
    query = sa.select(s.run_sources.c.screening_decision).where(
        s.run_sources.c.run_id == run_id, s.run_sources.c.source_id == source_id
    )
    if lock:
        query = query.with_for_update()
    row = (await conn.execute(query)).one_or_none()
    if row is None:
        raise ValueError("run/Source membership does not exist")
    if row[0] == "exclude":
        raise ValueError("excluded run/Source cannot acquire content")


async def _openalex_acquisition_identity(conn: AsyncConnection, source_id: UUID) -> str:
    rows = (
        await conn.execute(
            sa.select(s.source_identifiers.c.kind, s.source_identifiers.c.value).where(
                s.source_identifiers.c.source_id == source_id,
                s.source_identifiers.c.namespace == "openalex",
            )
        )
    ).all()
    return openalex_acquisition_identity(
        ExactSourceKey(kind, "openalex", value) for kind, value in rows
    )


class DocumentAcquisitionPersistence:
    """Two short operations; neither keeps a connection open during provider I/O."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load_acquisition_identity(
        self, run_id: str, source_id: UUID, provider_id: str
    ) -> str:
        if provider_id != "openalex":
            raise ValueError("document acquisition supports only OpenAlex")
        async with self._engine.connect() as conn:
            await _acquisition_membership(conn, run_id, source_id)
            return await _openalex_acquisition_identity(conn, source_id)

    async def commit_document_acquisition(
        self,
        run_id: str,
        document: SourceDocument,
        content: bytes | None,
        *,
        expected_identity: str,
    ) -> UUID:
        state = {
            "usable": "retrieved",
            "unavailable": "unavailable",
            "failed": "failed",
            "incomplete": "failed",
        }[document.status]
        async with self._engine.begin() as conn:
            # Discovery reconciliation locks Source before identifiers/membership.
            # Use the same order and hold the Source lock until the atomic commit.
            source_id = (
                await conn.execute(
                    sa.select(s.sources.c.source_id)
                    .where(s.sources.c.source_id == document.source_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if source_id is None:
                raise ValueError("Source does not exist")
            current_identity = await _openalex_acquisition_identity(conn, source_id)
            if current_identity != expected_identity:
                raise ValueError("Source acquisition identity changed during retrieval")
            await _acquisition_membership(conn, run_id, document.source_id, lock=True)
            document_id = await _record_source_document(conn, document, content)
            await conn.execute(
                s.run_sources.update()
                .where(
                    s.run_sources.c.run_id == run_id,
                    s.run_sources.c.source_id == document.source_id,
                )
                .values(processing_state=state)
            )
            return document_id


async def _document(conn: AsyncConnection, document_id: UUID) -> sa.RowMapping:
    row = (
        (
            await conn.execute(
                sa.select(s.source_documents).where(s.source_documents.c.document_id == document_id)
            )
        )
        .mappings()
        .one()
    )
    verify_content(row["content"], row["content_sha256"], usable=row["status"] == "usable")
    return row


async def load_source_document(
    engine: AsyncEngine, document_id: UUID
) -> tuple[SourceDocument, bytes | None]:
    async with engine.connect() as conn:
        row = await _document(conn, document_id)
        return SourceDocument(
            **{key: value for key, value in row.items() if key != "content"}
        ), row["content"]


async def load_extraction_document(
    engine: AsyncEngine, run_id: str, source_id: UUID, document_id: UUID
) -> tuple[SourceDocument, bytes]:
    async with engine.connect() as conn:
        await _acquisition_membership(conn, run_id, source_id)
        row = await _document(conn, document_id)
        if row["source_id"] != source_id or row["status"] != "usable":
            raise ValueError("extraction requires a usable document belonging to this Source")
        return SourceDocument(
            **{key: value for key, value in row.items() if key != "content"}
        ), row["content"]


async def _save_extraction(
    conn: AsyncConnection,
    extraction: Extraction,
    document: sa.RowMapping,
    configuration: bytes,
    publication_digest: str | None = None,
    raw_output: bytes | None = None,
) -> bool:
    if sha256(configuration).hexdigest() != extraction.configuration_sha256:
        raise ValueError("extraction configuration checksum mismatch")
    json_value(extraction)
    values: dict[str, Any] = {
        **asdict(extraction),
        "configuration": configuration,
        "source_id": document["source_id"],
        "document_status": document["status"],
        "record_provenance": json_value(extraction.record_provenance),
        "publication_digest": publication_digest,
        "raw_output": raw_output,
        "raw_output_sha256": sha256(raw_output).hexdigest() if raw_output is not None else None,
    }
    created = (
        await conn.execute(
            insert(s.extractions)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[s.extractions.c.extraction_id])
            .returning(s.extractions.c.extraction_id)
        )
    ).scalar_one_or_none()
    if created is not None:
        return True
    current = (
        (
            await conn.execute(
                sa.select(s.extractions)
                .where(s.extractions.c.extraction_id == extraction.extraction_id)
                .with_for_update()
            )
        )
        .mappings()
        .one()
    )
    if current["status"] not in {"queued", "running"}:
        if any(current[key] != value for key, value in values.items()):
            raise ImmutableRecordConflict(
                "finalized extraction UUID cannot be reused for a new result"
            )
        return False
    for key in ("run_id", "source_document_id", "purpose", "configuration_sha256", "configuration"):
        if current[key] != values[key]:
            raise ImmutableRecordConflict("extraction attempt identity changed")
    await conn.execute(
        s.extractions.update()
        .where(s.extractions.c.extraction_id == extraction.extraction_id)
        .values(**values)
    )
    return True


async def record_extraction(
    engine: AsyncEngine,
    extraction: Extraction,
    configuration: bytes,
    *,
    raw_output: bytes | None = None,
) -> None:
    """Record supplied pending/failed/review-needed attempts; accepted output uses publication."""
    if extraction.status == "accepted":
        raise ValueError("accepted output must use atomic evidence publication")
    async with engine.begin() as conn:
        document = await _document(conn, extraction.source_document_id)
        await _save_extraction(conn, extraction, document, configuration, raw_output=raw_output)


async def publish_accepted_extraction(
    engine: AsyncEngine,
    extraction: Extraction,
    configuration: bytes,
    studies: tuple[StudyRecord, ...],
    findings: tuple[FindingRecord, ...],
    *,
    raw_output: bytes | None = None,
    select_for_run: bool = False,
) -> None:
    if extraction.status != "accepted":
        raise ValueError("publication requires accepted extraction")
    publication: dict[str, object] = {
        "extraction": extraction,
        "studies": studies,
        "findings": findings,
    }
    if raw_output is not None:
        publication["raw_output_sha256"] = sha256(raw_output).hexdigest()
    publication_digest = digest(publication)
    async with engine.begin() as conn:
        document = await _document(conn, extraction.source_document_id)
        if document["status"] != "usable":
            raise ValueError("accepted evidence requires usable immutable content")
        if select_for_run:
            await _extraction_publication_membership(conn, extraction.run_id, document["source_id"])
        is_new = await _save_extraction(
            conn, extraction, document, configuration, publication_digest, raw_output
        )
        if not is_new:
            if select_for_run:
                await _select_published(conn, extraction, document["source_id"])
            return
        study_ids: set[UUID] = set()
        for study in studies:
            if (
                study.extraction_id != extraction.extraction_id
                or study.source_id != document["source_id"]
                or study.record_provenance.created_in_run_id != extraction.run_id
            ):
                raise ValueError(
                    "Study does not belong to this extraction, Source and creating run"
                )
            study_ids.add(study.study_id)
            data = json_value(study)
            for key in ("study_id", "source_id", "extraction_id"):
                del data[key]
            await conn.execute(
                s.studies.insert().values(
                    study_id=study.study_id,
                    source_id=study.source_id,
                    extraction_id=study.extraction_id,
                    data=data,
                )
            )
        for finding in findings:
            if (
                finding.source_study_id not in study_ids
                or finding.record_provenance.created_in_run_id != extraction.run_id
            ):
                raise ValueError("Finding does not belong to this publication")
            # A locator alone is useful draft data but cannot prove accepted content attribution.
            if not finding.evidence_anchors or any(
                not anchor.passage
                or not anchor.passage.strip()
                or anchor.passage.encode("utf-8") not in document["content"]
                for anchor in finding.evidence_anchors
            ):
                raise ValueError("accepted Finding requires exact passages in this document")
            data = json_value(finding)
            for key in ("finding_id", "source_study_id", "evidence_anchors"):
                del data[key]
            await conn.execute(
                s.findings.insert().values(
                    finding_id=finding.finding_id,
                    study_id=finding.source_study_id,
                    anchors=json_value(finding.evidence_anchors),
                    data=data,
                )
            )
        if select_for_run:
            await _select_published(conn, extraction, document["source_id"])


async def _extraction_publication_membership(
    conn: AsyncConnection, run_id: str, source_id: UUID
) -> None:
    row = (
        await conn.execute(
            sa.select(s.run_sources.c.screening_decision)
            .where(s.run_sources.c.run_id == run_id, s.run_sources.c.source_id == source_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None or row[0] == "exclude":
        raise ExtractionEligibilityChanged("run/Source membership or screening changed")


async def _select_published(conn: AsyncConnection, extraction: Extraction, source_id: UUID) -> None:
    # Called only after accepted evidence publication, under the locked membership.
    await conn.execute(
        s.run_sources.update()
        .where(s.run_sources.c.run_id == extraction.run_id, s.run_sources.c.source_id == source_id)
        .values(selected_extraction_id=extraction.extraction_id, processing_state="extracted")
    )


async def select_run_source_extraction(
    engine: AsyncEngine,
    run_id: str,
    source_id: UUID,
    extraction_id: UUID,
) -> None:
    async with engine.begin() as conn:
        accepted = (
            await conn.execute(
                sa.select(s.extractions.c.extraction_id).where(
                    s.extractions.c.extraction_id == extraction_id,
                    s.extractions.c.source_id == source_id,
                    s.extractions.c.status == "accepted",
                )
            )
        ).scalar_one_or_none()
        if accepted is None:
            raise ValueError("selection requires accepted evidence for this Source")
        # Stage 2 explicitly permits reuse of accepted evidence created in another run.
        updated = (
            await conn.execute(
                s.run_sources.update()
                .where(s.run_sources.c.run_id == run_id, s.run_sources.c.source_id == source_id)
                .values(selected_extraction_id=extraction_id)
                .returning(s.run_sources.c.source_id)
            )
        ).scalar_one_or_none()
        if updated is None:
            raise ValueError("run/Source membership does not exist")


async def set_processing_state(
    engine: AsyncEngine,
    run_id: str,
    source_id: UUID,
    state: Literal["discovered", "retrieved", "extracted", "excluded", "unavailable", "failed"],
) -> None:
    async with engine.begin() as conn:
        membership = (
            (
                await conn.execute(
                    sa.select(s.run_sources)
                    .where(s.run_sources.c.run_id == run_id, s.run_sources.c.source_id == source_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        if state == "extracted" and membership["selected_extraction_id"] is None:
            raise ValueError("extracted outcome requires an explicit accepted selection")
        await conn.execute(
            s.run_sources.update()
            .where(s.run_sources.c.run_id == run_id, s.run_sources.c.source_id == source_id)
            .values(processing_state=state)
        )


async def apply_screening_decision(engine: AsyncEngine, decision: ScreeningDecision) -> None:
    detail = json_value(decision)
    async with engine.begin() as conn:
        membership = (
            (
                await conn.execute(
                    sa.select(s.run_sources)
                    .where(
                        s.run_sources.c.run_id == decision.run_id,
                        s.run_sources.c.source_id == decision.source_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        values: dict[str, Any]
        if decision.study_id is not None:
            owned = (
                await conn.execute(
                    sa.select(s.studies.c.study_id).where(
                        s.studies.c.study_id == decision.study_id,
                        s.studies.c.source_id == decision.source_id,
                    )
                )
            ).scalar_one_or_none()
            if owned is None:
                raise ValueError("scoped screening Study must belong to this Source")
            values = {
                "scoped_screening": {
                    **membership["scoped_screening"],
                    str(decision.study_id): detail,
                }
            }
        else:
            values = {"screening_decision": decision.decision, "screening_detail": detail}
            if decision.decision == "exclude":
                values["processing_state"] = "excluded"
        await conn.execute(
            s.run_sources.update()
            .where(
                s.run_sources.c.run_id == decision.run_id,
                s.run_sources.c.source_id == decision.source_id,
            )
            .values(**values)
        )
