"""Versioned manifest for consumer-independent static research exports."""

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_atlas.domain.versioning import ProtocolReference
from research_atlas.schemas.research_records import ResearchRecords
from research_atlas.schemas.run_definition import RunDefinition


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

    bundle_schema_version: Literal["0.1"]
    records_schema_version: Literal["0.5"]
    bundle_id: str
    generated_at: datetime
    project_id: str
    protocol_references: tuple[ProtocolReference, ...]
    taxonomy_reference: str
    taxonomy_version: str
    contributing_run_ids: tuple[str, ...]
    counts: ExportCounts
    construct_registry_version: str
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
        content_files: tuple[ContentFile, ...] = (),
    ) -> Self:
        """Build a manifest whose records version and counts come from its records."""

        return cls(
            bundle_schema_version="0.1",
            records_schema_version=records.schema_version,
            bundle_id=bundle_id,
            generated_at=generated_at,
            project_id=project_id,
            protocol_references=protocol_references,
            taxonomy_reference=taxonomy_reference,
            taxonomy_version=taxonomy_version,
            contributing_run_ids=contributing_run_ids,
            counts=ExportCounts.from_records(records),
            construct_registry_version=construct_registry_version,
            content_files=content_files,
        )


class RunDefinitionSnapshot(BaseModel):
    """A validated run definition plus its portable project-owned reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str = Field(min_length=1)
    definition: RunDefinition


class ExportBundle(BaseModel):
    """In-memory representation that can be serialized into a static bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ExportBundleManifest
    run_definitions: tuple[RunDefinitionSnapshot, ...]
    records: ResearchRecords

    @model_validator(mode="after")
    def validate_manifest_against_records(self) -> Self:
        """Ensure the manifest cannot disagree with the bundled record payload."""

        if self.manifest.records_schema_version != self.records.schema_version:
            raise ValueError("manifest records_schema_version must match records schema_version")
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
        contributing_run_ids = set(self.manifest.contributing_run_ids)
        unexpected_run_ids = [
            run.run_id
            for run in self.records.research_runs
            if run.run_id not in contributing_run_ids
        ]
        if unexpected_run_ids:
            raise ValueError(
                "bundled ResearchRun IDs are absent from manifest contributing_run_ids: "
                f"{unexpected_run_ids}"
            )

        definition_ids = [snapshot.definition.run_id for snapshot in self.run_definitions]
        if len(definition_ids) != len(set(definition_ids)):
            raise ValueError("bundled RunDefinition run_id values must be unique")
        definitions_by_run_id = {
            snapshot.definition.run_id: snapshot for snapshot in self.run_definitions
        }
        if tuple(definition_ids) != self.manifest.contributing_run_ids:
            raise ValueError(
                "bundled RunDefinition run IDs and order must exactly match manifest "
                "contributing_run_ids"
            )

        run_metadata_errors: list[str] = []
        for run_id in self.manifest.contributing_run_ids:
            run = runs_by_id[run_id]
            snapshot = definitions_by_run_id[run_id]
            definition = snapshot.definition
            if definition.definition_status != "approved":
                run_metadata_errors.append(
                    f"contributing ResearchRun {run_id} requires an approved RunDefinition"
                )
            if definition.records_schema_version != self.records.schema_version:
                run_metadata_errors.append(
                    f"contributing ResearchRun {run_id} RunDefinition records_schema_version "
                    "must match bundled records schema_version"
                )
            for field_name, run_value, definition_value in (
                ("project_id", run.project_id, definition.project_id),
                (
                    "definition_schema_version",
                    run.definition_schema_version,
                    definition.schema_version,
                ),
                ("definition_reference", run.definition_reference, snapshot.reference),
                ("definition_fingerprint", run.definition_fingerprint, definition.fingerprint()),
                ("protocol_references", run.protocol_references, definition.protocol_references),
                ("taxonomy_reference", run.taxonomy_reference, definition.taxonomy.reference),
                ("taxonomy_version", run.taxonomy_version, definition.taxonomy.version),
            ):
                if run_value != definition_value:
                    run_metadata_errors.append(
                        f"contributing ResearchRun {run_id} {field_name} must match bundled "
                        f"RunDefinition; expected {definition_value!r}, got {run_value!r}"
                    )
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

        search_specs_by_run_id = {
            run_id: {
                spec.search_spec_id: spec for spec in snapshot.definition.search_plan.search_specs
            }
            for run_id, snapshot in definitions_by_run_id.items()
        }
        execution_errors: list[str] = []
        for execution in self.records.search_executions:
            specs = search_specs_by_run_id.get(execution.run_id)
            if specs is None:
                execution_errors.append(
                    f"SearchExecution {execution.search_execution_id} has no bundled RunDefinition"
                )
                continue
            spec = specs.get(execution.search_spec_id)
            if spec is None:
                execution_errors.append(
                    f"SearchExecution {execution.search_execution_id} references missing "
                    f"SearchSpec {execution.search_spec_id!r}"
                )
                continue
            for field_name, execution_value, spec_value in (
                ("provider_id", execution.provider_id, spec.provider_id),
                ("operation_id", execution.operation_id, spec.operation_id),
                ("exact_query", execution.exact_query, spec.exact_query),
                ("parameters", execution.parameters, spec.parameters),
            ):
                if execution_value != spec_value:
                    execution_errors.append(
                        f"SearchExecution {execution.search_execution_id} {field_name} must match "
                        f"approved SearchSpec {execution.search_spec_id}; expected {spec_value!r}, "
                        f"got {execution_value!r}"
                    )
            if execution.requested_limit != spec.requested_limit:
                execution_errors.append(
                    f"SearchExecution {execution.search_execution_id} requested_limit must match "
                    f"approved SearchSpec {execution.search_spec_id}; expected "
                    f"{spec.requested_limit!r}, got {execution.requested_limit!r}"
                )
        if execution_errors:
            raise ValueError("; ".join(execution_errors))

        screening_errors: list[str] = []
        for decision in self.records.screening_decisions:
            snapshot = definitions_by_run_id.get(decision.run_id)
            if snapshot is None:
                screening_errors.append(
                    f"ScreeningDecision {decision.decision_id} has no bundled RunDefinition"
                )
                continue
            plan = snapshot.definition.screening_plan
            if decision.stage not in plan.stages:
                screening_errors.append(
                    f"ScreeningDecision {decision.decision_id} stage {decision.stage!r} "
                    "is not declared in the approved ScreeningPlan"
                )
            undeclared_reasons = sorted(set(decision.reason_codes) - set(plan.reason_codes))
            if undeclared_reasons:
                screening_errors.append(
                    f"ScreeningDecision {decision.decision_id} reason_codes are not declared "
                    f"in the approved ScreeningPlan: {undeclared_reasons}"
                )
        if screening_errors:
            raise ValueError("; ".join(screening_errors))
        return self


def checksum_file(path: Path) -> str:
    """Return a SHA-256 checksum without imposing a bundle storage layout."""

    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
