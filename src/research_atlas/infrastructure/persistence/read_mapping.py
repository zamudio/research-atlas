"""Reconstitute trusted persisted records; JSON remains internal to this adapter."""

from datetime import datetime
from typing import Any

import sqlalchemy as sa

from research_atlas.application.read_models import EvidenceContext, FindingEvidence, SourceDisplay
from research_atlas.domain.content import EvidenceAnchor, Extraction, SourceDocument
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.evidence import FindingRecord, Insight
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import ExternalIdentifier, StudyRecord


def provenance(value: dict[str, Any]) -> RecordProvenance:
    data = dict(value)
    for key in ("created_at", "reviewed_at"):
        if data.get(key) is not None:
            data[key] = datetime.fromisoformat(data[key])
    return RecordProvenance(**data)


def source_display(row: sa.RowMapping) -> SourceDisplay:
    data: dict[str, Any] = row["reported"] or {}
    return SourceDisplay(
        row["source_id"],
        row["display_observation_id"],
        data.get("title"),
        tuple(credit_record(credit) for credit in data.get("credits", ())),
        data.get("year"),
        data.get("source_type"),
        data.get("source_url"),
        tuple(ExternalIdentifier(**item) for item in data.get("identifiers", ())),
    )


def credit_record(value: dict[str, Any]) -> BibliographicCredit:
    data = dict(value)
    data["external_identifiers"] = tuple(tuple(pair) for pair in data["external_identifiers"])
    return BibliographicCredit(**data)


def study_record(row: sa.RowMapping) -> StudyRecord:
    data = dict(row["study_data"])
    data["record_provenance"] = provenance(data["record_provenance"])
    return StudyRecord(
        study_id=row["study_id"],
        source_id=row["source_id"],
        extraction_id=row["extraction_id"],
        **data,
    )


def finding_record(row: sa.RowMapping) -> FindingRecord:
    data = dict(row["finding_data"])
    data["record_provenance"] = provenance(data["record_provenance"])
    for key in ("moderator_and_subgroup_notes", "reviewer_notes", "limitations"):
        data[key] = tuple(data.get(key, ()))
    return FindingRecord(
        finding_id=row["finding_id"],
        source_study_id=row["study_id"],
        evidence_anchors=tuple(EvidenceAnchor(**anchor) for anchor in row["anchors"]),
        **data,
    )


def extraction_record(row: sa.RowMapping) -> Extraction:
    data: dict[str, Any] = {
        name: row["extraction_" + name] for name in Extraction.__dataclass_fields__
    }
    data["record_provenance"] = provenance(data["record_provenance"])
    return Extraction(**data)


def document_record(row: sa.RowMapping) -> SourceDocument:
    return SourceDocument(
        **{name: row["document_" + name] for name in SourceDocument.__dataclass_fields__}
    )


def evidence_context(row: sa.RowMapping) -> EvidenceContext:
    return EvidenceContext(
        study_record(row), extraction_record(row), document_record(row), source_display(row)
    )


def finding_evidence(row: sa.RowMapping) -> FindingEvidence:
    return FindingEvidence(finding_record(row), evidence_context(row))


def insight_record(row: sa.RowMapping) -> Insight:
    return Insight(
        row["insight_id"],
        row["run_id"],
        row["claim"],
        row["configuration_sha256"],
        provenance(row["record_provenance"]),
        tuple(row["qualifications"]),
        tuple(row["uncertainty_and_limitations"]),
        tuple(row["generalizability_notes"]),
    )
