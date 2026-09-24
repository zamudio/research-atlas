"""Versioned manifest for consumer-independent static research exports."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_atlas.domain.versioning import ProtocolReference
from research_atlas.schemas.research_records import ResearchRecords


class ContentFile(BaseModel):
    """A bundle content file and its integrity metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: str = "application/json"


class ExportCounts(BaseModel):
    """Counts that help consumers verify bundle expectations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sources: int = Field(ge=0)
    studies: int = Field(ge=0)
    findings: int = Field(ge=0)
    evidence_assessments: int = Field(ge=0)
    constructs: int = Field(ge=0)
    measurements: int = Field(ge=0)
    interventions: int = Field(ge=0)
    application_candidates: int = Field(ge=0)
    decision_implications: int = Field(ge=0)
    research_runs: int = Field(ge=0)
    search_executions: int = Field(ge=0)
    source_discoveries: int = Field(ge=0)
    screening_decisions: int = Field(ge=0)

    @classmethod
    def from_records(cls, records: ResearchRecords) -> Self:
        """Derive every count from the record collections."""

        return cls(
            sources=len(records.sources),
            studies=len(records.studies),
            findings=len(records.findings),
            evidence_assessments=len(records.evidence_assessments),
            constructs=len(records.constructs),
            measurements=len(records.measurements),
            interventions=len(records.interventions),
            application_candidates=len(records.application_candidates),
            decision_implications=len(records.decision_implications),
            research_runs=len(records.research_runs),
            search_executions=len(records.search_executions),
            source_discoveries=len(records.source_discoveries),
            screening_decisions=len(records.screening_decisions),
        )


class ExportBundleManifest(BaseModel):
    """Portable, versioned metadata for a static research export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    bundle_id: str
    generated_at: datetime
    project_id: str
    protocol_references: tuple[ProtocolReference, ...]
    taxonomy_reference: str
    taxonomy_version: str
    contributing_run_ids: tuple[str, ...]
    counts: ExportCounts
    construct_registry_version: str
    research_questions: tuple[str, ...]
    content_files: tuple[ContentFile, ...] = ()

    @classmethod
    def for_records(
        cls,
        records: ResearchRecords,
        *,
        bundle_id: str,
        generated_at: datetime,
        project_id: str,
        protocol_references: tuple[ProtocolReference, ...],
        taxonomy_reference: str,
        taxonomy_version: str,
        contributing_run_ids: tuple[str, ...],
        construct_registry_version: str,
        research_questions: tuple[str, ...],
        content_files: tuple[ContentFile, ...] = (),
    ) -> Self:
        """Build a manifest whose schema version and counts come from its records."""

        return cls(
            schema_version=records.schema_version,
            bundle_id=bundle_id,
            generated_at=generated_at,
            project_id=project_id,
            protocol_references=protocol_references,
            taxonomy_reference=taxonomy_reference,
            taxonomy_version=taxonomy_version,
            contributing_run_ids=contributing_run_ids,
            counts=ExportCounts.from_records(records),
            construct_registry_version=construct_registry_version,
            research_questions=research_questions,
            content_files=content_files,
        )


class ExportBundle(BaseModel):
    """In-memory representation that can be serialized into a static bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ExportBundleManifest
    records: ResearchRecords

    @model_validator(mode="after")
    def validate_manifest_against_records(self) -> Self:
        """Ensure the manifest cannot disagree with the bundled record payload."""

        if self.manifest.schema_version != self.records.schema_version:
            raise ValueError("manifest schema_version must match records schema_version")
        expected_counts = ExportCounts.from_records(self.records)
        if self.manifest.counts != expected_counts:
            raise ValueError(
                "manifest counts must match records; "
                f"expected {expected_counts.model_dump()}, got {self.manifest.counts.model_dump()}"
            )

        runs_by_id = {run.run_id: run for run in self.records.research_runs}
        missing_run_ids = [
            run_id for run_id in self.manifest.contributing_run_ids if run_id not in runs_by_id
        ]
        if missing_run_ids:
            raise ValueError(
                "manifest contributing_run_ids reference missing ResearchRun IDs: "
                f"{missing_run_ids}"
            )

        run_metadata_errors: list[str] = []
        for run_id in self.manifest.contributing_run_ids:
            run = runs_by_id[run_id]
            for field_name, run_value, manifest_value in (
                ("project_id", run.project_id, self.manifest.project_id),
                (
                    "protocol_references",
                    run.protocol_references,
                    self.manifest.protocol_references,
                ),
                ("taxonomy_reference", run.taxonomy_reference, self.manifest.taxonomy_reference),
                ("taxonomy_version", run.taxonomy_version, self.manifest.taxonomy_version),
            ):
                if run_value != manifest_value:
                    run_metadata_errors.append(
                        f"contributing ResearchRun {run_id} {field_name} must match manifest "
                        f"{field_name}; expected {manifest_value!r}, got {run_value!r}"
                    )
        if run_metadata_errors:
            raise ValueError("; ".join(run_metadata_errors))
        return self


def checksum_file(path: Path) -> str:
    """Return a SHA-256 checksum without imposing a bundle storage layout."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
