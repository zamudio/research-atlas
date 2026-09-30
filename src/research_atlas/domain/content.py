"""Immutable content versions and extraction attempts, without acquisition or execution services."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from research_atlas.domain.provenance import RecordProvenance


def require_sha256(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("expected a lowercase SHA-256 digest")


def require_tool_versions(provenance: RecordProvenance) -> None:
    if bool(provenance.tool_name) != bool(provenance.tool_version):
        raise ValueError("tool identity requires name and version")
    if bool(provenance.model_name) != bool(provenance.model_version):
        raise ValueError("model identity requires name and version")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One immutable content artifact/version; checksum covers the exact anchorable bytes.

    A changed payload or parsed representation receives a new document_id. A URL
    is retrieval context, never content identity. Failed attempts may lack bytes.
    """

    document_id: UUID
    source_id: UUID
    content_kind: str
    retrieval_context: str
    retrieved_at: datetime
    status: Literal["usable", "unavailable", "failed", "incomplete"]
    content_sha256: str | None = None
    source_url: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.content_kind.strip() or not self.retrieval_context.strip():
            raise ValueError("document kind and retrieval context are required")
        if self.content_sha256 is not None:
            require_sha256(self.content_sha256)
        if self.status == "usable" and self.content_sha256 is None:
            raise ValueError("usable documents require an immutable content checksum")


@dataclass(frozen=True, slots=True)
class Extraction:
    """One attempt against one document version, with explicit acceptance.

    configuration_sha256 identifies the retained instructions AND settings.
    Re-extraction always gets a new identity; finalized results are not replaced.
    """

    extraction_id: UUID
    run_id: str
    source_document_id: UUID
    purpose: str
    configuration_sha256: str
    record_provenance: RecordProvenance
    status: Literal["queued", "running", "accepted", "review_needed", "failed", "rejected"]
    validation_outcome: Literal["pending", "passed", "failed"] = "pending"
    review_outcome: Literal["pending", "accepted", "rejected", "not_required"] = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_sha256(self.configuration_sha256)
        require_tool_versions(self.record_provenance)
        if not self.run_id.strip() or not self.purpose.strip():
            raise ValueError("extraction run and purpose are required")
        if self.run_id != self.record_provenance.created_in_run_id:
            raise ValueError("extraction provenance must identify the creating run")
        if self.status != "queued" and self.started_at is None:
            raise ValueError("started extraction requires started_at")
        if self.status not in {"queued", "running"} and self.completed_at is None:
            raise ValueError("finalized extraction requires completed_at")
        if self.completed_at is not None and (
            self.started_at is None or self.completed_at < self.started_at
        ):
            raise ValueError("extraction completion must follow start")
        if self.status in {"queued", "running"} and self.completed_at is not None:
            raise ValueError("active extraction cannot have completion time")
        if self.status == "accepted" and (
            self.validation_outcome != "passed"
            or self.review_outcome not in {"accepted", "not_required"}
        ):
            raise ValueError(
                "accepted extraction requires passed validation and review disposition"
            )
        if self.status == "review_needed" and self.review_outcome not in {"pending", "rejected"}:
            raise ValueError("review-needed output cannot already be accepted")


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    """A passage and/or locator in the Study's Extraction's exact SourceDocument.

    Locator is plain text (for example section, page or table); no page is mandatory.
    """

    passage: str | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        if not ((self.passage and self.passage.strip()) or (self.locator and self.locator.strip())):
            raise ValueError("evidence anchor requires passage or locator")
