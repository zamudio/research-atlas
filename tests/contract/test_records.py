from datetime import UTC, datetime
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
from research_workbench.domain.decisions import ArchitectureCandidate
from research_workbench.domain.evidence import EvidenceAssessment, EvidenceDimension
from research_workbench.domain.studies import SourceProvenance, StudyRecord
from research_workbench.schemas.research_records import ResearchRecords

STUDY_ID = UUID("b2bdbd04-bf4f-4d6c-aad2-cdf9ded46562")


def representative_records() -> ResearchRecords:
    study = StudyRecord(
        study_id=STUDY_ID,
        title="Representative study",
        authors=("A. Researcher",),
        year=2025,
        study_type="randomized experiment",
        population_summary="Adult volunteers",
        domain_summary="Example task",
        setting_summary="Laboratory",
        sample_summary="N=100",
        provenance=(SourceProvenance(provider="manual", provider_record_id="source-1"),),
    )
    construct = ConstructRecord(
        construct_id="retrieval-strength",
        canonical_name="Retrieval strength",
        aliases=(),
        definitions=(SourcedDefinition(text="Example definition", source_ids=(str(STUDY_ID),)),),
        timescales=("session",),
        candidate_moderators=(),
        candidate_observables=(CandidateObservable(description="Delayed response accuracy"),),
        product_observability_status="indirect",
        inference_risks=("Accuracy has multiple causes",),
        candidate_architecture_destinations=("policy",),
        review_status="investigate",
    )
    measurement = MeasurementRecord(
        measurement_id=UUID("d1324238-2259-4381-8bf7-aaf9a426a18b"),
        source_study_id=STUDY_ID,
        target_construct_id=construct.construct_id,
        name="Delayed test",
        operationalization="Proportion correct after a delay",
        instrument_or_signal="Item responses",
        timescale="one week",
    )
    evidence = EvidenceAssessment(
        evidence_id="evidence-001",
        subject_id=construct.construct_id,
        supporting_study_ids=(STUDY_ID,),
        direction="positive",
        summary="Representative result for contract testing",
        dimensions=(
            EvidenceDimension(
                name="measurement validity",
                level="limited",
                rationale="A single outcome is not construct-complete.",
            ),
        ),
        uncertainty_and_limitations=("Single study",),
        generalizability_notes=("Other populations not assessed",),
    )
    candidate = ArchitectureCandidate(
        candidate_id="candidate-001",
        subject_id=construct.construct_id,
        observable_by_product="indirectly",
        proposed_raw_signals=("item response",),
        inference_risks=("Incorrect responses are ambiguous",),
        actionability="may alter practice selection",
        proposed_destination="policy",
        rationale="Use aggregate task evidence without assigning a trait.",
        confidence="limited",
        status="investigate",
        linked_evidence_ids=(evidence.evidence_id,),
        linked_study_ids=(STUDY_ID,),
    )
    return ResearchRecords(
        schema_version="0.1",
        studies=(study,),
        constructs=(construct,),
        measurements=(measurement,),
        evidence_assessments=(evidence,),
        architecture_candidates=(candidate,),
    )


def test_research_records_round_trip_json() -> None:
    records = representative_records()

    restored = ResearchRecords.model_validate_json(records.model_dump_json())

    assert restored == records


def test_architecture_candidate_traces_to_evidence_and_study() -> None:
    records = representative_records()
    candidate = records.architecture_candidates[0]
    evidence = records.evidence_assessments[0]

    assert candidate.linked_evidence_ids == (evidence.evidence_id,)
    assert set(candidate.linked_study_ids) <= set(evidence.supporting_study_ids)
    assert set(evidence.supporting_study_ids) <= {study.study_id for study in records.studies}


def test_export_manifest_round_trip_and_required_versions() -> None:
    manifest = ExportBundleManifest(
        schema_version="0.1",
        bundle_id="ai-tutor-foundations-0.1",
        generated_at=datetime(2026, 9, 24, tzinfo=UTC),
        project_id="ai-tutor",
        protocol_version="0.1",
        taxonomy_version="0.1",
        contributing_run_ids=("run-001",),
        counts=ExportCounts(
            sources=1,
            evidence_assessments=1,
            constructs=1,
            product_implications=0,
        ),
        construct_registry_version="0.1",
        research_questions=("What supports durable learning?",),
        content_files=(ContentFile(path="records.json", sha256="a" * 64),),
    )

    restored = ExportBundleManifest.model_validate_json(manifest.model_dump_json())

    assert restored == manifest

    incomplete = manifest.model_dump()
    del incomplete["protocol_version"]
    with pytest.raises(ValidationError):
        ExportBundleManifest.model_validate(incomplete)

    bundle = ExportBundle(manifest=manifest, records=representative_records())
    assert ExportBundle.model_validate_json(bundle.model_dump_json()) == bundle


def test_import_boundary_requires_study_provenance() -> None:
    payload = representative_records().model_dump(mode="json")
    del payload["studies"][0]["provenance"]

    with pytest.raises(ValidationError):
        ResearchRecords.model_validate(payload)
