"""Versioned manifest for consumer-independent static research exports."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_workbench.domain.versioning import ProtocolVersions
from research_workbench.schemas.research_records import ResearchRecords


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
    architecture_candidates: int = Field(ge=0)
    product_implications: int = Field(ge=0)
    research_runs: int = Field(ge=0)

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
            architecture_candidates=len(records.architecture_candidates),
            product_implications=len(records.product_implications),
            research_runs=len(records.research_runs),
        )


class ExportBundleManifest(BaseModel):
    """Portable, versioned metadata for a static research export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    bundle_id: str
    generated_at: datetime
    project_id: str
    protocol_versions: ProtocolVersions
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
        protocol_versions: ProtocolVersions,
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
            protocol_versions=protocol_versions,
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
        return self


def checksum_file(path: Path) -> str:
    """Return a SHA-256 checksum without imposing a bundle storage layout."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
