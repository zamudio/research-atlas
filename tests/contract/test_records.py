from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from research_workbench.application.export.bundle import (
    ContentFile,
    ExportBundle,
    ExportBundleManifest,
    ExportCounts,
)
from research_workbench.domain.constructs import (
    CandidateObservable,
    ConstructRecord,
    MeasurementRecord,
    SourcedDefinition,
)
from research_workbench.domain.decisions import ArchitectureCandidate, ProductImplication
from research_workbench.domain.evidence import (
    EvidenceAssessment,
    EvidenceDimension,
    FindingRecord,
)
from research_workbench.domain.provenance import RecordProvenance
from research_workbench.domain.studies import (
    InterventionRecord,
    ResearchRun,
    SourceProvenance,
    SourceRecord,
    StudyRecord,
)
from research_workbench.domain.versioning import ProtocolVersions
from research_workbench.schemas.research_records import ResearchRecords

SOURCE_ID = UUID("19ab3dc6-f09f-49df-aadc-357e0746658b")
STUDY_ID = UUID("b2bdbd04-bf4f-4d6c-aad2-cdf9ded46562")
SECOND_STUDY_ID = UUID("687d27d2-a76d-4213-a57d-74676db15840")
MEASUREMENT_ID = UUID("d1324238-2259-4381-8bf7-aaf9a426a18b")
INTERVENTION_ID = UUID("01392873-e2cd-49be-9cc4-4c2753589a87")
FINDING_ID = UUID("e377c619-84fa-4a58-9fa2-8624596447d5")
NOW = datetime(2026, 9, 24, tzinfo=UTC)
PROTOCOL_VERSIONS = ProtocolVersions(
    extraction="0.3",
    evidence_assessment="0.1",
    architecture_promotion="0.1",
)


def representative_records() -> ResearchRecords:
    manual_provenance = RecordProvenance(
        created_in_run_id="run-contract-test",
        created_at=NOW,
        extraction_method="manual",
        reviewer="reviewer@example.test",
        review_status="reviewed",
        reviewed_at=NOW,
    )
    source = SourceRecord(
        source_id=SOURCE_ID,
        title="Representative publication",
        authors=("A. Researcher",),
        year=2025,
        source_type="journal article",
        provider_provenance=(
            SourceProvenance(provider="reference-library", provider_record_id="source-1"),
        ),
    )
    studies = (
        StudyRecord(
            study_id=STUDY_ID,
            source_id=SOURCE_ID,
            study_label="Study 1",
            study_type="randomized experiment",
            population_summary="Adult volunteers",
            domain_summary="Example task",
            setting_summary="Laboratory",
            sample_summary="N=100",
            record_provenance=manual_provenance,
        ),
        StudyRecord(
            study_id=SECOND_STUDY_ID,
            source_id=SOURCE_ID,
            study_label="Study 2",
            study_type="replication",
            population_summary="Adult volunteers",
            domain_summary="Example task",
            setting_summary="Online",
            sample_summary="N=150",
            record_provenance=manual_provenance,
        ),
    )
    construct = ConstructRecord(
        construct_id="retrieval-strength",
        canonical_name="Retrieval strength",
        aliases=(),
        definitions=(SourcedDefinition(text="Example definition", source_ids=(SOURCE_ID,)),),
        timescales=("session",),
        candidate_moderators=(),
        candidate_observables=(CandidateObservable(description="Delayed response accuracy"),),
        product_observability_status="indirect",
        inference_risks=("Accuracy has multiple causes",),
        candidate_architecture_destinations=("policy",),
        review_status="investigate",
        record_provenance=manual_provenance,
    )
    measurement = MeasurementRecord(
        measurement_id=MEASUREMENT_ID,
        source_study_id=STUDY_ID,
        target_construct_id=construct.construct_id,
        name="Delayed test",
        operationalization="Proportion correct after a delay",
        instrument_or_signal="Item responses",
        timescale="one week",
        record_provenance=manual_provenance,
    )
    intervention = InterventionRecord(
        intervention_id=INTERVENTION_ID,
        source_study_id=STUDY_ID,
        description="Retrieval practice",
        comparator="Restudy",
        target_population="Adult volunteers",
        context="Laboratory task",
        outcomes_studied=("Delayed test accuracy",),
        record_provenance=manual_provenance,
    )
    finding = FindingRecord(
        finding_id=FINDING_ID,
        source_study_id=STUDY_ID,
        question_investigated="Does retrieval practice improve delayed accuracy?",
        outcome_investigated="Delayed test accuracy",
        result_summary="Retrieval practice produced higher delayed accuracy than restudy.",
        direction="positive",
        status="reported",
        linked_measurement_ids=(MEASUREMENT_ID,),
        linked_intervention_ids=(INTERVENTION_ID,),
        effect_estimate="standardized mean difference reported by authors",
        uncertainty="confidence interval reported in the source",
        limitations=("Single task",),
        record_provenance=manual_provenance,
    )
    evidence = EvidenceAssessment(
        evidence_id="evidence-001",
        claim="Retrieval practice improves delayed accuracy relative to restudy.",
        supporting_finding_ids=(FINDING_ID,),
        direction="positive",
        summary="Representative synthesis for contract testing",
        dimensions=(
            EvidenceDimension(
                name="measurement validity",
                level="limited",
                rationale="A single outcome is not construct-complete.",
            ),
        ),
        uncertainty_and_limitations=("Single supporting finding",),
        generalizability_notes=("Other populations not assessed",),
        record_provenance=manual_provenance,
    )
    candidate = ArchitectureCandidate(
        candidate_id="candidate-001",
        observable_by_product="indirectly",
        proposed_raw_signals=("item response",),
        inference_risks=("Incorrect responses are ambiguous",),
        actionability="may alter practice selection",
        proposed_destination="policy",
        rationale="Use aggregate task evidence without assigning a trait.",
        confidence="limited",
        status="investigate",
        linked_evidence_ids=(evidence.evidence_id,),
        record_provenance=manual_provenance,
    )
    implication = ProductImplication(
        implication_id="implication-001",
        statement="Consider retrieval opportunities in practice selection.",
        rationale="The candidate remains traceable to assessed findings.",
        destination="policy",
        status="investigate",
        linked_candidate_ids=(candidate.candidate_id,),
        linked_evidence_ids=(evidence.evidence_id,),
        record_provenance=manual_provenance,
    )
    research_run = ResearchRun(
        run_id="run-contract-test",
        project_id="contract-test",
        run_type="schema validation",
        purpose="Exercise the record contracts",
        research_questions=("What supports durable learning?",),
        protocol_versions=PROTOCOL_VERSIONS,
        taxonomy_version="0.1",
        search_strategy="Fixture data only",
        search_queries=(),
        inclusion_criteria=("Representative fixture",),
        exclusion_criteria=(),
        started_at=NOW,
        completed_at=NOW,
        included_study_ids=(STUDY_ID, SECOND_STUDY_ID),
    )
    return ResearchRecords(
        schema_version="0.3",
        sources=(source,),
        studies=studies,
        constructs=(construct,),
        measurements=(measurement,),
        interventions=(intervention,),
        findings=(finding,),
        evidence_assessments=(evidence,),
        architecture_candidates=(candidate,),
        product_implications=(implication,),
        research_runs=(research_run,),
    )


def test_one_source_can_report_multiple_studies() -> None:
    records = representative_records()

    assert len(records.sources) == 1
    assert len(records.studies) == 2
    assert {study.source_id for study in records.studies} == {records.sources[0].source_id}


def test_findings_are_distinct_from_evidence_assessments() -> None:
    records = representative_records()

    finding = records.findings[0]
    assessment = records.evidence_assessments[0]
    assert assessment.supporting_finding_ids == (finding.finding_id,)
    assert finding.result_summary != assessment.summary


def test_evidence_assessment_can_assess_claim_without_construct_link() -> None:
    assessment = representative_records().evidence_assessments[0]

    assert assessment.claim
    assert assessment.linked_construct_ids == ()


def test_evidence_assessment_can_link_valid_constructs() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["evidence_assessments"][0]["linked_construct_ids"] = ["retrieval-strength"]

    records = ResearchRecords.model_validate(payload)

    assert records.evidence_assessments[0].linked_construct_ids == ("retrieval-strength",)


def test_architecture_candidate_relies_on_evidence_without_construct_subject() -> None:
    candidate = representative_records().architecture_candidates[0]

    assert candidate.linked_evidence_ids == ("evidence-001",)
    assert candidate.linked_construct_ids == ()
    assert not hasattr(candidate, "subject_id")


def test_record_provenance_is_provider_neutral_and_extensible() -> None:
    manual = RecordProvenance(
        created_in_run_id="run-1",
        created_at=NOW,
        extraction_method="manual",
    )
    assisted = RecordProvenance(
        created_in_run_id="run-1",
        created_at=NOW,
        extraction_method="LLM-assisted",
        tool_name="local-review-tool",
        tool_version="2.1",
        model_name="model-x",
        model_version="2026-09",
    )

    assert manual.extraction_method != assisted.extraction_method
    assert assisted.tool_name == "local-review-tool"
    assert assisted.model_name == "model-x"


@pytest.mark.parametrize(
    "collection",
    (
        "studies",
        "constructs",
        "measurements",
        "interventions",
        "findings",
        "evidence_assessments",
        "architecture_candidates",
        "product_implications",
    ),
)
def test_extracted_and_derived_records_require_provenance(collection: str) -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    del payload[collection][0]["record_provenance"]

    with pytest.raises(ValidationError, match="record_provenance"):
        ResearchRecords.model_validate(payload)


def test_study_record_has_required_process_provenance() -> None:
    study = representative_records().studies[0]

    assert study.record_provenance.created_in_run_id == "run-contract-test"


def test_dangling_provenance_run_is_rejected_clearly() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["findings"][0]["record_provenance"]["created_in_run_id"] = "missing-run"

    with pytest.raises(
        ValidationError,
        match=r"FindingRecord .* record_provenance\.created_in_run_id reference missing IDs",
    ):
        ResearchRecords.model_validate(payload)


def test_valid_linked_records_round_trip_json() -> None:
    records = representative_records()

    restored = ResearchRecords.model_validate_json(records.model_dump_json())

    assert restored == records


def test_source_import_boundary_requires_provider_provenance() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    del payload["sources"][0]["provider_provenance"]

    with pytest.raises(ValidationError):
        ResearchRecords.model_validate(payload)


def test_duplicate_ids_are_rejected() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["sources"].append(payload["sources"][0])

    with pytest.raises(ValidationError, match="duplicate source IDs"):
        ResearchRecords.model_validate(payload)


@pytest.mark.parametrize(
    ("collection", "field", "bad_value"),
    (
        ("studies", "source_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("measurements", "source_study_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("measurements", "target_construct_id", "missing-construct"),
        ("interventions", "source_study_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("findings", "source_study_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("findings", "linked_measurement_ids", ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]),
        ("findings", "linked_intervention_ids", ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]),
        (
            "evidence_assessments",
            "supporting_finding_ids",
            ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
        ),
        ("evidence_assessments", "linked_construct_ids", ["missing-construct"]),
        ("architecture_candidates", "linked_construct_ids", ["missing-construct"]),
        ("architecture_candidates", "linked_evidence_ids", ["missing-evidence"]),
    ),
)
def test_dangling_references_are_rejected(
    collection: str, field: str, bad_value: str | list[str]
) -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload[collection][0][field] = bad_value

    with pytest.raises(ValidationError, match="reference missing IDs"):
        ResearchRecords.model_validate(payload)


def test_export_counts_are_derived_and_cannot_disagree() -> None:
    records = representative_records()
    manifest = ExportBundleManifest.for_records(
        records,
        bundle_id="contract-test-0.3",
        generated_at=NOW,
        project_id="contract-test",
        protocol_versions=PROTOCOL_VERSIONS,
        taxonomy_version="0.1",
        contributing_run_ids=(),
        construct_registry_version="0.3",
        research_questions=("What supports durable learning?",),
        content_files=(ContentFile(path="records.json", sha256="a" * 64),),
    )

    assert manifest.counts == ExportCounts.from_records(records)
    bundle = ExportBundle(manifest=manifest, records=records)
    assert ExportBundle.model_validate_json(bundle.model_dump_json()) == bundle

    bad_manifest = manifest.model_dump(mode="json")
    bad_manifest["counts"]["findings"] = 99
    with pytest.raises(ValidationError, match="manifest counts must match records"):
        ExportBundle.model_validate({"manifest": bad_manifest, "records": records})

    incomplete_manifest = manifest.model_dump(mode="json")
    del incomplete_manifest["protocol_versions"]
    with pytest.raises(ValidationError):
        ExportBundleManifest.model_validate(incomplete_manifest)


def test_protocol_versions_round_trip_through_run_and_manifest() -> None:
    records = representative_records()
    restored_records = ResearchRecords.model_validate_json(records.model_dump_json())
    manifest = ExportBundleManifest.for_records(
        records,
        bundle_id="protocol-versions",
        generated_at=NOW,
        project_id="contract-test",
        protocol_versions=PROTOCOL_VERSIONS,
        taxonomy_version="0.1",
        contributing_run_ids=("run-contract-test",),
        construct_registry_version="0.3",
        research_questions=("What supports durable learning?",),
    )
    restored_manifest = ExportBundleManifest.model_validate_json(manifest.model_dump_json())

    assert restored_records.research_runs[0].protocol_versions == PROTOCOL_VERSIONS
    assert restored_manifest.protocol_versions == PROTOCOL_VERSIONS


def test_full_product_decision_chain_needs_no_redundant_study_links() -> None:
    records = representative_records()
    implication = records.product_implications[0]
    candidate = records.architecture_candidates[0]
    evidence = records.evidence_assessments[0]
    finding = records.findings[0]
    study = records.studies[0]

    assert implication.linked_candidate_ids == (candidate.candidate_id,)
    assert candidate.linked_evidence_ids == (evidence.evidence_id,)
    assert evidence.supporting_finding_ids == (finding.finding_id,)
    assert finding.source_study_id == study.study_id
    assert study.source_id == records.sources[0].source_id
    assert not hasattr(implication, "linked_study_ids")
    assert not hasattr(candidate, "linked_study_ids")


def test_frozen_domain_records_have_no_obvious_mutable_containers() -> None:
    records = representative_records()
    domain_records = (
        *records.sources,
        *records.studies,
        *records.constructs,
        *records.measurements,
        *records.interventions,
        *records.findings,
        *records.evidence_assessments,
        *records.architecture_candidates,
        *records.product_implications,
    )

    for record in domain_records:
        for item in fields(record):
            assert not isinstance(getattr(record, item.name), (dict, list))
