"""Versioned manifest for consumer-independent static research exports."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

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
    evidence_assessments: int = Field(ge=0)
    constructs: int = Field(ge=0)
    product_implications: int = Field(ge=0)


class ExportBundleManifest(BaseModel):
    """Portable, versioned metadata for a static research export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    bundle_id: str
    generated_at: datetime
    project_id: str
    protocol_version: str
    taxonomy_version: str
    contributing_run_ids: tuple[str, ...]
    counts: ExportCounts
    construct_registry_version: str
    research_questions: tuple[str, ...]
    content_files: tuple[ContentFile, ...] = ()


class ExportBundle(BaseModel):
    """In-memory representation that can be serialized into a static bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ExportBundleManifest
    records: ResearchRecords


def checksum_file(path: Path) -> str:
    """Return a SHA-256 checksum without imposing a bundle storage layout."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
