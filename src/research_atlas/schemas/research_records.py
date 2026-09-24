"""Pydantic boundaries for importing and exporting trusted domain records."""

from collections.abc import Hashable, Iterable
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from research_atlas.domain.constructs import ConstructRecord, MeasurementRecord
from research_atlas.domain.decisions import ArchitectureCandidate, ProductImplication
from research_atlas.domain.evidence import EvidenceAssessment, FindingRecord
from research_atlas.domain.studies import (
    InterventionRecord,
    ResearchRun,
    SourceRecord,
    StudyRecord,
)


def _duplicate_values(values: Iterable[Hashable]) -> set[Hashable]:
    seen: set[Hashable] = set()
    duplicates: set[Hashable] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _missing_values(values: Iterable[Hashable], valid_values: Iterable[Hashable]) -> set[Hashable]:
    return set(values) - set(valid_values)


class ResearchRecords(BaseModel):
    """A validated, serializable collection of normalized research records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    sources: tuple[SourceRecord, ...] = ()
    studies: tuple[StudyRecord, ...] = ()
    constructs: tuple[ConstructRecord, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    interventions: tuple[InterventionRecord, ...] = ()
    findings: tuple[FindingRecord, ...] = ()
    evidence_assessments: tuple[EvidenceAssessment, ...] = ()
    architecture_candidates: tuple[ArchitectureCandidate, ...] = ()
    product_implications: tuple[ProductImplication, ...] = ()
    research_runs: tuple[ResearchRun, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Reject duplicate identities and dangling typed references in one place."""

        identity_groups = (
            ("source", (record.source_id for record in self.sources)),
            ("study", (record.study_id for record in self.studies)),
            ("construct", (record.construct_id for record in self.constructs)),
            ("measurement", (record.measurement_id for record in self.measurements)),
            ("intervention", (record.intervention_id for record in self.interventions)),
            ("finding", (record.finding_id for record in self.findings)),
            ("evidence assessment", (record.evidence_id for record in self.evidence_assessments)),
            (
                "architecture candidate",
                (record.candidate_id for record in self.architecture_candidates),
            ),
            (
                "product implication",
                (record.implication_id for record in self.product_implications),
            ),
            ("research run", (record.run_id for record in self.research_runs)),
        )
        errors: list[str] = []
        for label, values in identity_groups:
            duplicates = _duplicate_values(values)
            if duplicates:
                errors.append(f"duplicate {label} IDs: {sorted(map(str, duplicates))}")

        source_ids = {record.source_id for record in self.sources}
        study_ids = {record.study_id for record in self.studies}
        construct_ids = {record.construct_id for record in self.constructs}
        measurement_ids = {record.measurement_id for record in self.measurements}
        intervention_ids = {record.intervention_id for record in self.interventions}
        finding_ids = {record.finding_id for record in self.findings}
        evidence_ids = {record.evidence_id for record in self.evidence_assessments}
        candidate_ids = {record.candidate_id for record in self.architecture_candidates}
        run_ids = {record.run_id for record in self.research_runs}

        def check(label: str, values: Iterable[Hashable], valid: Iterable[Hashable]) -> None:
            missing = _missing_values(values, valid)
            if missing:
                errors.append(f"{label} reference missing IDs: {sorted(map(str, missing))}")

        for record in self.studies:
            check(f"StudyRecord {record.study_id} source_id", (record.source_id,), source_ids)
        for record in self.constructs:
            for definition in record.definitions:
                check(
                    f"ConstructRecord {record.construct_id} definition source_ids",
                    definition.source_ids,
                    source_ids,
                )
        for record in self.measurements:
            check(
                f"MeasurementRecord {record.measurement_id} source_study_id",
                (record.source_study_id,),
                study_ids,
            )
            check(
                f"MeasurementRecord {record.measurement_id} target_construct_id",
                (record.target_construct_id,),
                construct_ids,
            )
        for record in self.interventions:
            check(
                f"InterventionRecord {record.intervention_id} source_study_id",
                (record.source_study_id,),
                study_ids,
            )
        for record in self.findings:
            check(
                f"FindingRecord {record.finding_id} source_study_id",
                (record.source_study_id,),
                study_ids,
            )
            check(
                f"FindingRecord {record.finding_id} linked_measurement_ids",
                record.linked_measurement_ids,
                measurement_ids,
            )
            check(
                f"FindingRecord {record.finding_id} linked_intervention_ids",
                record.linked_intervention_ids,
                intervention_ids,
            )
        for record in self.evidence_assessments:
            check(
                f"EvidenceAssessment {record.evidence_id} linked_construct_ids",
                record.linked_construct_ids,
                construct_ids,
            )
            check(
                f"EvidenceAssessment {record.evidence_id} supporting_finding_ids",
                record.supporting_finding_ids,
                finding_ids,
            )
            check(
                f"EvidenceAssessment {record.evidence_id} contradictory_finding_ids",
                record.contradictory_finding_ids,
                finding_ids,
            )
            check(
                f"EvidenceAssessment {record.evidence_id} null_finding_ids",
                record.null_finding_ids,
                finding_ids,
            )
        for record in self.architecture_candidates:
            check(
                f"ArchitectureCandidate {record.candidate_id} linked_construct_ids",
                record.linked_construct_ids,
                construct_ids,
            )
            check(
                f"ArchitectureCandidate {record.candidate_id} linked_evidence_ids",
                record.linked_evidence_ids,
                evidence_ids,
            )
        for record in self.product_implications:
            check(
                f"ProductImplication {record.implication_id} linked_candidate_ids",
                record.linked_candidate_ids,
                candidate_ids,
            )
            check(
                f"ProductImplication {record.implication_id} linked_evidence_ids",
                record.linked_evidence_ids,
                evidence_ids,
            )
        for record in self.research_runs:
            check(
                f"ResearchRun {record.run_id} included_study_ids",
                record.included_study_ids,
                study_ids,
            )

        provenance_references = (
            *(
                ("StudyRecord", record.study_id, record.record_provenance.created_in_run_id)
                for record in self.studies
            ),
            *(
                ("ConstructRecord", record.construct_id, record.record_provenance.created_in_run_id)
                for record in self.constructs
            ),
            *(
                (
                    "MeasurementRecord",
                    record.measurement_id,
                    record.record_provenance.created_in_run_id,
                )
                for record in self.measurements
            ),
            *(
                (
                    "InterventionRecord",
                    record.intervention_id,
                    record.record_provenance.created_in_run_id,
                )
                for record in self.interventions
            ),
            *(
                ("FindingRecord", record.finding_id, record.record_provenance.created_in_run_id)
                for record in self.findings
            ),
            *(
                (
                    "EvidenceAssessment",
                    record.evidence_id,
                    record.record_provenance.created_in_run_id,
                )
                for record in self.evidence_assessments
            ),
            *(
                (
                    "ArchitectureCandidate",
                    record.candidate_id,
                    record.record_provenance.created_in_run_id,
                )
                for record in self.architecture_candidates
            ),
            *(
                (
                    "ProductImplication",
                    record.implication_id,
                    record.record_provenance.created_in_run_id,
                )
                for record in self.product_implications
            ),
        )
        for record_type, record_id, created_in_run_id in provenance_references:
            check(
                f"{record_type} {record_id} record_provenance.created_in_run_id",
                (created_in_run_id,),
                run_ids,
            )

        if errors:
            raise ValueError("; ".join(errors))
        return self
