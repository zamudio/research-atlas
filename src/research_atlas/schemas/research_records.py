"""Pydantic boundary for versioned, referentially sound research records."""

from collections.abc import Hashable, Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from research_atlas.domain.constructs import ConstructRecord, MeasurementRecord
from research_atlas.domain.decisions import ApplicationCandidate, DecisionImplication
from research_atlas.domain.evidence import EvidenceAssessment, FindingRecord
from research_atlas.domain.execution import ScreeningDecision, SearchExecution, SourceDiscovery
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
    """A v0.4 collection of normalized evidence and research-process records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.4"] = "0.4"
    sources: tuple[SourceRecord, ...] = ()
    studies: tuple[StudyRecord, ...] = ()
    constructs: tuple[ConstructRecord, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    interventions: tuple[InterventionRecord, ...] = ()
    findings: tuple[FindingRecord, ...] = ()
    evidence_assessments: tuple[EvidenceAssessment, ...] = ()
    application_candidates: tuple[ApplicationCandidate, ...] = ()
    decision_implications: tuple[DecisionImplication, ...] = ()
    research_runs: tuple[ResearchRun, ...] = ()
    search_executions: tuple[SearchExecution, ...] = ()
    source_discoveries: tuple[SourceDiscovery, ...] = ()
    screening_decisions: tuple[ScreeningDecision, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Reject duplicate identities, dangling references, and inconsistent chains."""

        identity_groups = (
            ("source", (record.source_id for record in self.sources)),
            ("study", (record.study_id for record in self.studies)),
            ("construct", (record.construct_id for record in self.constructs)),
            ("measurement", (record.measurement_id for record in self.measurements)),
            ("intervention", (record.intervention_id for record in self.interventions)),
            ("finding", (record.finding_id for record in self.findings)),
            ("evidence assessment", (record.evidence_id for record in self.evidence_assessments)),
            (
                "application candidate",
                (record.candidate_id for record in self.application_candidates),
            ),
            (
                "decision implication",
                (record.implication_id for record in self.decision_implications),
            ),
            ("research run", (record.run_id for record in self.research_runs)),
            ("search execution", (record.search_execution_id for record in self.search_executions)),
            ("source discovery", (record.discovery_id for record in self.source_discoveries)),
            ("screening decision", (record.decision_id for record in self.screening_decisions)),
        )
        errors: list[str] = []
        for label, values in identity_groups:
            duplicates = _duplicate_values(values)
            if duplicates:
                errors.append(f"duplicate {label} IDs: {sorted(map(str, duplicates))}")

        source_ids = {record.source_id for record in self.sources}
        studies_by_id = {record.study_id: record for record in self.studies}
        study_ids = set(studies_by_id)
        construct_ids = {record.construct_id for record in self.constructs}
        measurement_ids = {record.measurement_id for record in self.measurements}
        intervention_ids = {record.intervention_id for record in self.interventions}
        finding_ids = {record.finding_id for record in self.findings}
        evidence_ids = {record.evidence_id for record in self.evidence_assessments}
        candidate_ids = {record.candidate_id for record in self.application_candidates}
        run_ids = {record.run_id for record in self.research_runs}
        executions_by_id = {record.search_execution_id: record for record in self.search_executions}
        execution_ids = set(executions_by_id)
        decisions_by_id = {record.decision_id: record for record in self.screening_decisions}
        decision_ids = set(decisions_by_id)

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
            for field_name, values in (
                ("supporting_finding_ids", record.supporting_finding_ids),
                ("contradictory_finding_ids", record.contradictory_finding_ids),
                ("null_finding_ids", record.null_finding_ids),
            ):
                check(f"EvidenceAssessment {record.evidence_id} {field_name}", values, finding_ids)
        for record in self.application_candidates:
            check(
                f"ApplicationCandidate {record.candidate_id} linked_construct_ids",
                record.linked_construct_ids,
                construct_ids,
            )
            check(
                f"ApplicationCandidate {record.candidate_id} linked_evidence_ids",
                record.linked_evidence_ids,
                evidence_ids,
            )
        for record in self.decision_implications:
            check(
                f"DecisionImplication {record.implication_id} linked_candidate_ids",
                record.linked_candidate_ids,
                candidate_ids,
            )
            check(
                f"DecisionImplication {record.implication_id} linked_evidence_ids",
                record.linked_evidence_ids,
                evidence_ids,
            )

        for record in self.search_executions:
            check(f"SearchExecution {record.search_execution_id} run_id", (record.run_id,), run_ids)
        for record in self.source_discoveries:
            check(f"SourceDiscovery {record.discovery_id} run_id", (record.run_id,), run_ids)
            check(
                f"SourceDiscovery {record.discovery_id} source_id", (record.source_id,), source_ids
            )
            check(
                f"SourceDiscovery {record.discovery_id} search_execution_id",
                (record.search_execution_id,),
                execution_ids,
            )
            execution = executions_by_id.get(record.search_execution_id)
            if execution is not None and execution.run_id != record.run_id:
                errors.append(
                    f"SourceDiscovery {record.discovery_id} run_id must match its "
                    "SearchExecution run_id"
                )
            if execution is not None and execution.status != "succeeded":
                errors.append(
                    f"SourceDiscovery {record.discovery_id} requires a succeeded SearchExecution"
                )

        superseded_ids: list[str] = []
        for record in self.screening_decisions:
            check(f"ScreeningDecision {record.decision_id} run_id", (record.run_id,), run_ids)
            check(
                f"ScreeningDecision {record.decision_id} source_id",
                (record.source_id,),
                source_ids,
            )
            if record.record_provenance.created_in_run_id != record.run_id:
                errors.append(
                    f"ScreeningDecision {record.decision_id} provenance run must match run_id"
                )
            if record.study_id is not None:
                check(
                    f"ScreeningDecision {record.decision_id} study_id",
                    (record.study_id,),
                    study_ids,
                )
                study = studies_by_id.get(record.study_id)
                if study is not None and study.source_id != record.source_id:
                    errors.append(
                        f"ScreeningDecision {record.decision_id} study_id must belong to source_id"
                    )
            if record.supersedes_decision_id is not None:
                superseded_ids.append(record.supersedes_decision_id)
                check(
                    f"ScreeningDecision {record.decision_id} supersedes_decision_id",
                    (record.supersedes_decision_id,),
                    decision_ids,
                )
                previous = decisions_by_id.get(record.supersedes_decision_id)
                if previous is record:
                    errors.append(f"ScreeningDecision {record.decision_id} cannot supersede itself")
                elif previous is not None and (
                    previous.run_id,
                    previous.source_id,
                    previous.study_id,
                    previous.stage,
                ) != (record.run_id, record.source_id, record.study_id, record.stage):
                    errors.append(
                        f"ScreeningDecision {record.decision_id} may only supersede a decision "
                        "for the same subject and stage"
                    )
        duplicate_superseded = _duplicate_values(superseded_ids)
        if duplicate_superseded:
            errors.append(
                "screening decisions cannot be superseded more than once: "
                f"{sorted(map(str, duplicate_superseded))}"
            )
        for decision in self.screening_decisions:
            visited = {decision.decision_id}
            parent_id = decision.supersedes_decision_id
            while parent_id is not None:
                if parent_id in visited:
                    errors.append(f"ScreeningDecision supersession cycle includes {parent_id}")
                    break
                visited.add(parent_id)
                parent = decisions_by_id.get(parent_id)
                parent_id = parent.supersedes_decision_id if parent is not None else None

        provenance_records = (
            *(
                ("StudyRecord", r.study_id, r.record_provenance.created_in_run_id)
                for r in self.studies
            ),
            *(
                ("ConstructRecord", r.construct_id, r.record_provenance.created_in_run_id)
                for r in self.constructs
            ),
            *(
                ("MeasurementRecord", r.measurement_id, r.record_provenance.created_in_run_id)
                for r in self.measurements
            ),
            *(
                ("InterventionRecord", r.intervention_id, r.record_provenance.created_in_run_id)
                for r in self.interventions
            ),
            *(
                ("FindingRecord", r.finding_id, r.record_provenance.created_in_run_id)
                for r in self.findings
            ),
            *(
                ("EvidenceAssessment", r.evidence_id, r.record_provenance.created_in_run_id)
                for r in self.evidence_assessments
            ),
            *(
                ("ApplicationCandidate", r.candidate_id, r.record_provenance.created_in_run_id)
                for r in self.application_candidates
            ),
            *(
                ("DecisionImplication", r.implication_id, r.record_provenance.created_in_run_id)
                for r in self.decision_implications
            ),
            *(
                ("ScreeningDecision", r.decision_id, r.record_provenance.created_in_run_id)
                for r in self.screening_decisions
            ),
        )
        for record_type, record_id, created_in_run_id in provenance_records:
            check(
                f"{record_type} {record_id} record_provenance.created_in_run_id",
                (created_in_run_id,),
                run_ids,
            )

        if errors:
            raise ValueError("; ".join(errors))
        return self
