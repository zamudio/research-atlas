"""Acceptance cases E/F/G: selection, exact content provenance, explicit evidence roles."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid7

import pytest

from research_atlas.domain.content import EvidenceAnchor, Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord, Insight, InsightFinding
from research_atlas.domain.execution import RunSource
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import StudyRecord

NOW = datetime(2026, 9, 29, tzinfo=UTC)
CONFIG = sha256(b"instructions and settings").hexdigest()
PROVENANCE = RecordProvenance("run-1", NOW, "manual", tool_name="review-tool", tool_version="1")


def document() -> SourceDocument:
    return SourceDocument(
        uuid7(),
        uuid7(),
        "full_text",
        "publisher XML parsed to UTF-8 text",
        NOW,
        "usable",
        sha256(b"No clear difference was detected.").hexdigest(),
    )


def extraction(doc: SourceDocument) -> Extraction:
    return Extraction(
        uuid7(),
        "run-1",
        doc.document_id,
        "studies and findings",
        CONFIG,
        PROVENANCE,
        "accepted",
        "passed",
        "accepted",
        NOW,
        NOW,
    )


def test_document_status_and_content_version_validation() -> None:
    doc = document()
    with pytest.raises(ValueError, match="checksum"):
        replace(doc, content_sha256=None)
    with pytest.raises(ValueError, match="SHA-256"):
        replace(doc, content_sha256="bad")
    unavailable = replace(doc, status="unavailable", content_sha256=None)
    assert unavailable.content_sha256 is None
    newer = replace(doc, document_id=uuid7(), content_sha256=sha256(b"changed content").hexdigest())
    assert newer.document_id != doc.document_id and newer.content_sha256 != doc.content_sha256


def test_reextraction_keeps_original_result_and_explicitly_selects_one() -> None:
    doc = document()
    first = extraction(doc)
    second = extraction(doc)
    attempts = {item.extraction_id: item for item in (first, second)}
    membership = RunSource("run-1", doc.source_id)
    selected = membership.select_extraction(first, doc)
    reselected = selected.select_extraction(second, doc)
    assert len(attempts) == 2
    assert selected.selected_extraction_id == first.extraction_id
    assert reselected.selected_extraction_id == second.extraction_id
    assert attempts[first.extraction_id] is first
    assert selected.processing_state == membership.processing_state == "discovered"
    # Progress is explicit; a failed later attempt does not erase accepted evidence.
    failed_later = replace(reselected, processing_state="failed")
    assert failed_later.selected_extraction_id == second.extraction_id
    # Evidence reads join through selected_extraction_id, never union all reruns.
    study_ids = {first.extraction_id: (uuid7(),), second.extraction_id: (uuid7(),)}
    assert reselected.selected_extraction_id is not None
    assert len(study_ids[reselected.selected_extraction_id]) == 1
    with pytest.raises(FrozenInstanceError):
        first.status = "failed"  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValueError, match="accepted extraction"):
        membership.select_extraction(
            replace(second, status="review_needed", review_outcome="pending"), doc
        )
    with pytest.raises(ValueError, match="Source"):
        RunSource("run-1", uuid7()).select_extraction(first, doc)


def test_extraction_status_validation_distinguishes_failed_review_and_accepted() -> None:
    accepted = extraction(document())
    with pytest.raises(ValueError, match="passed validation"):
        replace(accepted, validation_outcome="failed")
    with pytest.raises(ValueError, match="completed_at"):
        replace(accepted, completed_at=None)
    with pytest.raises(ValueError, match="creating run"):
        replace(accepted, run_id="wrong-run")
    with pytest.raises(ValueError, match="name and version"):
        replace(
            accepted, record_provenance=replace(PROVENANCE, model_name="model", model_version=None)
        )
    failed = replace(
        accepted, status="failed", validation_outcome="failed", review_outcome="pending"
    )
    review = replace(accepted, status="review_needed", review_outcome="pending")
    assert failed.status != review.status != accepted.status


def test_finding_traces_to_exact_document_with_anchor_without_page_requirement() -> None:
    doc = document()
    attempt = extraction(doc)
    study = StudyRecord(
        uuid7(),
        doc.source_id,
        attempt.extraction_id,
        "trial",
        "adults",
        "learning",
        "classroom",
        "N=40",
        PROVENANCE,
    )
    finding = FindingRecord(
        uuid7(),
        study.study_id,
        "Difference?",
        "Retention",
        "No clear difference",
        "null",
        "reported",
        PROVENANCE,
        (EvidenceAnchor(passage="No clear difference was detected.", locator="Results"),),
    )
    assert finding.source_study_id == study.study_id
    assert study.extraction_id == attempt.extraction_id
    assert attempt.source_document_id == doc.document_id
    assert finding.evidence_anchors[0].passage is not None
    assert doc.content_sha256 == sha256(finding.evidence_anchors[0].passage.encode()).hexdigest()
    with pytest.raises(ValueError, match="anchor"):
        replace(finding, evidence_anchors=())
    with pytest.raises(ValueError, match="passage or locator"):
        EvidenceAnchor()


def test_null_finding_does_not_choose_its_insight_relationship() -> None:
    insight = Insight(
        uuid7(),
        "run-1",
        "The benefit remains uncertain",
        CONFIG,
        PROVENANCE,
        uncertainty_and_limitations=("Small sample",),
    )
    finding = FindingRecord(
        uuid7(),
        uuid7(),
        "Difference?",
        "Retention",
        "No clear difference",
        "null",
        "reported",
        PROVENANCE,
        (EvidenceAnchor(passage="No clear difference was detected."),),
    )
    finding_id = finding.finding_id
    assert finding.direction == "null"
    # Same null Finding can play different roles for different claims.
    relationships = (
        InsightFinding(insight.insight_id, finding_id, "contextual", "Describes uncertainty"),
        InsightFinding(uuid7(), finding_id, "supporting", "Supports the claim of imprecision"),
        InsightFinding(
            uuid7(), finding_id, "contradicting", "Explicit appraisal against a universal claim"
        ),
    )
    assert {link.relationship for link in relationships} == {
        "contextual",
        "supporting",
        "contradicting",
    }
    with pytest.raises(ValueError, match="rationale"):
        replace(relationships[0], rationale="")
