from dataclasses import fields, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from research_atlas.application.export.bundle import (
    ContentFile,
    ExportBundle,
    ExportBundleManifest,
    ExportCounts,
    RunDefinitionSnapshot,
)
from research_atlas.domain.constructs import (
    CandidateObservable,
    ConstructRecord,
    MeasurementRecord,
    SourcedDefinition,
)
from research_atlas.domain.decisions import ApplicationCandidate, DecisionImplication
from research_atlas.domain.evidence import (
    EvidenceAssessment,
    EvidenceDimension,
    FindingRecord,
    current_evidence_assessments,
)
from research_atlas.domain.execution import (
    ScreeningDecision,
    SearchExecution,
    SearchParameter,
    SourceDiscovery,
    current_screening_decisions,
)
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.domain.studies import (
    InterventionRecord,
    ResearchRun,
    SourceProvenance,
    SourceRecord,
    StudyRecord,
)
from research_atlas.domain.versioning import ProtocolReference
from research_atlas.schemas.research_records import ResearchRecords
from research_atlas.schemas.run_definition import RunDefinition

SOURCE_ID = UUID("19ab3dc6-f09f-49df-aadc-357e0746658b")
OTHER_SOURCE_ID = UUID("56e2d281-e693-4949-b0ff-268afbc250b1")
STUDY_ID = UUID("b2bdbd04-bf4f-4d6c-aad2-cdf9ded46562")
SECOND_STUDY_ID = UUID("687d27d2-a76d-4213-a57d-74676db15840")
MEASUREMENT_ID = UUID("d1324238-2259-4381-8bf7-aaf9a426a18b")
INTERVENTION_ID = UUID("01392873-e2cd-49be-9cc4-4c2753589a87")
FINDING_ID = UUID("e377c619-84fa-4a58-9fa2-8624596447d5")
NOW = datetime(2026, 9, 24, tzinfo=UTC)
PROTOCOL_REFERENCES = (
    ProtocolReference("extraction", "0.3", "extraction"),
    ProtocolReference("screening", "0.1", "screening"),
    ProtocolReference("evidence-assessment", "0.1", "synthesis"),
)
DEFINITION_REFERENCE = "projects/contract-test/runs/example.yaml"


def representative_definition() -> RunDefinition:
    return RunDefinition.model_validate(
        {
            "schema_version": "0.2",
            "records_schema_version": "0.5",
            "definition_status": "approved",
            "project_id": "contract-test",
            "run_id": "run-contract-test",
            "label": "Contract test",
            "run_type": "test",
            "purpose": "Exercise portable bundle integrity.",
            "research_questions": [{"question_id": "RQ1", "text": "What is supported?"}],
            "scope": {},
            "search_plan": {
                "strategy": "Execute three approved logical searches.",
                "search_specs": [
                    {
                        "search_spec_id": "spec-1",
                        "label": "First search",
                        "query_intent": "First intent",
                        "execution_ready": True,
                        "provider_id": "openalex",
                        "operation_id": "openalex.search",
                        "exact_query": '"exact query one"',
                        "parameters": [{"name": "filter", "value": "type:review"}],
                        "requested_limit": 20,
                    },
                    {
                        "search_spec_id": "spec-2",
                        "label": "Second search",
                        "query_intent": "Second intent",
                        "execution_ready": True,
                        "provider_id": "openalex",
                        "operation_id": "openalex.search",
                        "exact_query": '"exact query two"',
                        "requested_limit": 20,
                    },
                    {
                        "search_spec_id": "spec-3",
                        "label": "Third search",
                        "query_intent": "Third intent",
                        "execution_ready": True,
                        "provider_id": "semantic_scholar",
                        "operation_id": "semantic_scholar.bulk",
                        "exact_query": '"exact query three"',
                        "requested_limit": 20,
                    },
                ],
            },
            "screening_plan": {
                "stages": ["relevance", "study-eligibility"],
                "inclusion_criteria": ["Relevant"],
                "reason_codes": ["meets_scope"],
            },
            "stopping_rule": {"rule_type": "complete", "description": "Test complete."},
            "protocol_references": [
                {
                    "protocol_id": reference.protocol_id,
                    "version": reference.version,
                    "phase": reference.phase,
                }
                for reference in PROTOCOL_REFERENCES
            ],
            "taxonomy": {
                "reference": "projects/contract-test/taxonomy.md",
                "version": "0.1",
            },
            "evidence_strategy": {"strategy": "Assess evidence."},
            "expected_outputs": ["records"],
        }
    )


def representative_records() -> ResearchRecords:
    definition = representative_definition()
    provenance = RecordProvenance(
        created_in_run_id="run-contract-test",
        created_at=NOW,
        creation_method="manual",
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
            SourceProvenance("reference-library", "source-1"),
            SourceProvenance("openalex", "W1"),
        ),
    )
    other_source = SourceRecord(
        source_id=OTHER_SOURCE_ID,
        title="Another publication",
        authors=("B. Researcher",),
        year=2024,
        source_type="journal article",
        provider_provenance=(SourceProvenance("reference-library", "source-2"),),
    )
    studies = (
        StudyRecord(
            study_id=STUDY_ID,
            source_id=SOURCE_ID,
            study_type="randomized experiment",
            population_summary="Adult volunteers",
            domain_summary="Example task",
            setting_summary="Laboratory",
            sample_summary="N=100",
            record_provenance=provenance,
            study_label="Study 1",
        ),
        StudyRecord(
            study_id=SECOND_STUDY_ID,
            source_id=SOURCE_ID,
            study_type="replication",
            population_summary="Adult volunteers",
            domain_summary="Example task",
            setting_summary="Online",
            sample_summary="N=150",
            record_provenance=provenance,
            study_label="Study 2",
        ),
    )
    construct = ConstructRecord(
        construct_id="example-construct",
        canonical_name="Example construct",
        aliases=(),
        definitions=(SourcedDefinition("Example definition", (SOURCE_ID,)),),
        timescales=("session",),
        candidate_moderators=(),
        candidate_observables=(CandidateObservable("Recorded outcome"),),
        inference_risks=("Accuracy has multiple causes",),
        review_status="investigate",
        record_provenance=provenance,
    )
    measurement = MeasurementRecord(
        measurement_id=MEASUREMENT_ID,
        source_study_id=STUDY_ID,
        target_construct_id=construct.construct_id,
        name="Example measure",
        operationalization="Recorded outcome value",
        instrument_or_signal="Observation record",
        timescale="one interval",
        record_provenance=provenance,
    )
    intervention = InterventionRecord(
        intervention_id=INTERVENTION_ID,
        source_study_id=STUDY_ID,
        description="Example intervention",
        comparator="Example comparator",
        target_population="Adult volunteers",
        context="Laboratory task",
        outcomes_studied=("Recorded outcome",),
        record_provenance=provenance,
    )
    finding = FindingRecord(
        finding_id=FINDING_ID,
        source_study_id=STUDY_ID,
        question_investigated="Does the intervention change the recorded outcome?",
        outcome_investigated="Recorded outcome",
        result_summary="The intervention produced a higher value than the comparator.",
        direction="positive",
        status="reported",
        record_provenance=provenance,
        linked_measurement_ids=(MEASUREMENT_ID,),
        linked_intervention_ids=(INTERVENTION_ID,),
    )
    evidence = EvidenceAssessment(
        evidence_id="evidence-001",
        claim="The intervention improves the recorded outcome.",
        supporting_finding_ids=(FINDING_ID,),
        direction="positive",
        summary="Representative synthesis",
        dimensions=(EvidenceDimension("measurement validity", "limited", "One measure"),),
        uncertainty_and_limitations=("Single supporting finding",),
        generalizability_notes=("Other populations not assessed",),
        record_provenance=provenance,
    )
    candidate = ApplicationCandidate(
        candidate_id="candidate-001",
        observability="indirect",
        proposed_raw_signals=("recorded observation",),
        inference_risks=("The observation may have multiple causes",),
        actionability="may alter a consumer decision",
        proposed_destination="project-supplied-destination",
        rationale="Use aggregate evidence without unsupported inference.",
        confidence="limited",
        status="investigate",
        linked_evidence_ids=(evidence.evidence_id,),
        record_provenance=provenance,
    )
    implication = DecisionImplication(
        implication_id="implication-001",
        statement="Consider the intervention when making the decision.",
        rationale="The candidate remains traceable to assessed findings.",
        destination="project-supplied-destination",
        status="investigate",
        linked_candidate_ids=(candidate.candidate_id,),
        linked_evidence_ids=(evidence.evidence_id,),
        record_provenance=provenance,
    )
    run = ResearchRun(
        run_id="run-contract-test",
        project_id="contract-test",
        definition_schema_version="0.2",
        definition_fingerprint=definition.fingerprint(),
        definition_reference=DEFINITION_REFERENCE,
        status="completed",
        protocol_references=PROTOCOL_REFERENCES,
        taxonomy_reference="projects/contract-test/taxonomy.md",
        taxonomy_version="0.1",
        started_at=NOW,
        completed_at=NOW,
    )
    executions = (
        SearchExecution(
            "search-1",
            run.run_id,
            "spec-1",
            "openalex",
            "openalex.search",
            '"exact query one"',
            (SearchParameter("filter", "type:review"),),
            20,
            NOW,
            NOW,
            "succeeded",
            provider_result_count=1,
        ),
        SearchExecution(
            "search-2",
            run.run_id,
            "spec-2",
            "openalex",
            "openalex.search",
            '"exact query two"',
            (),
            20,
            NOW,
            NOW,
            "succeeded",
            provider_result_count=1,
        ),
        SearchExecution(
            "search-failed",
            run.run_id,
            "spec-3",
            "semantic_scholar",
            "semantic_scholar.bulk",
            '"exact query three"',
            (),
            20,
            NOW,
            NOW,
            "failed",
            error_type="http_status",
            error_status_code=429,
            error_message="rate limited",
        ),
    )
    discoveries = (
        SourceDiscovery("discovery-1", "search-1", run.run_id, SOURCE_ID, NOW, "W1", 1),
        SourceDiscovery("discovery-2", "search-2", run.run_id, SOURCE_ID, NOW, "W1", 3),
    )
    decisions = (
        ScreeningDecision(
            "decision-1", run.run_id, SOURCE_ID, "relevance", "uncertain", (), provenance
        ),
        ScreeningDecision(
            "decision-2",
            run.run_id,
            SOURCE_ID,
            "relevance",
            "include",
            ("meets_scope",),
            provenance,
            rationale="Full text confirms relevance.",
            supersedes_decision_id="decision-1",
        ),
        ScreeningDecision(
            "decision-3",
            run.run_id,
            SOURCE_ID,
            "study-eligibility",
            "include",
            (),
            provenance,
            study_id=STUDY_ID,
        ),
    )
    return ResearchRecords(
        sources=(source, other_source),
        studies=studies,
        constructs=(construct,),
        measurements=(measurement,),
        interventions=(intervention,),
        findings=(finding,),
        evidence_assessments=(evidence,),
        application_candidates=(candidate,),
        decision_implications=(implication,),
        research_runs=(run,),
        search_executions=executions,
        source_discoveries=discoveries,
        screening_decisions=decisions,
    )


def representative_manifest(records: ResearchRecords) -> ExportBundleManifest:
    return ExportBundleManifest.for_records(
        records,
        bundle_id="contract-test-0.5",
        generated_at=NOW,
        project_id="contract-test",
        protocol_references=PROTOCOL_REFERENCES,
        taxonomy_reference="projects/contract-test/taxonomy.md",
        taxonomy_version="0.1",
        contributing_run_ids=("run-contract-test",),
        construct_registry_version="0.5",
        content_files=(ContentFile(path="records.json", sha256="a" * 64),),
    )


def representative_bundle(records: ResearchRecords | None = None) -> ExportBundle:
    records = records or representative_records()
    return ExportBundle(
        manifest=representative_manifest(records),
        run_definitions=(
            RunDefinitionSnapshot(
                reference=DEFINITION_REFERENCE,
                definition=representative_definition(),
            ),
        ),
        records=records,
    )


def test_records_v05_and_bundle_v01_round_trip_and_export_counts() -> None:
    records = representative_records()
    restored = ResearchRecords.model_validate_json(records.model_dump_json())
    bundle = representative_bundle(records)
    bundle_restored = ExportBundle.model_validate_json(bundle.model_dump_json())

    assert restored == records
    assert bundle_restored == bundle
    assert bundle.manifest.bundle_schema_version == "0.1"
    assert bundle.manifest.records_schema_version == "0.5"
    assert "research_questions" not in bundle.manifest.model_dump()
    assert bundle.manifest.counts == ExportCounts.from_records(records)
    assert bundle.manifest.counts.search_executions == 3
    assert bundle.manifest.counts.source_discoveries == 2
    assert bundle.manifest.counts.screening_decisions == 3


def test_records_reject_unsupported_schema_version() -> None:
    payload = representative_records().model_dump(mode="json")
    payload["schema_version"] = "0.4"

    with pytest.raises(ValidationError):
        ResearchRecords.model_validate(payload)


def test_construct_is_epistemic_and_application_chain_is_optional() -> None:
    records = representative_records()
    construct = records.constructs[0]

    assert not hasattr(construct, "product_observability_status")
    assert not hasattr(construct, "candidate_architecture_destinations")
    epistemic_only = records.model_copy(
        update={"application_candidates": (), "decision_implications": ()}
    )
    assert ResearchRecords.model_validate(epistemic_only.model_dump(mode="json"))


def test_application_chain_references_evidence_without_rewriting_it() -> None:
    records = representative_records()
    candidate = records.application_candidates[0]
    implication = records.decision_implications[0]

    assert candidate.observability == "indirect"
    assert candidate.linked_evidence_ids == (records.evidence_assessments[0].evidence_id,)
    assert implication.linked_candidate_ids == (candidate.candidate_id,)


def test_evidence_supersession_is_append_only_and_current_state_is_derived() -> None:
    records = representative_records()
    original = records.evidence_assessments[0]
    revised = replace(
        original,
        evidence_id="evidence-002",
        summary="Revised synthesis",
        supersedes_evidence_id=original.evidence_id,
    )
    updated = ResearchRecords.model_validate(
        records.model_copy(update={"evidence_assessments": (original, revised)}).model_dump(
            mode="json"
        )
    )

    assert current_evidence_assessments(updated.evidence_assessments) == (revised,)


@pytest.mark.parametrize(
    ("supersedes_id", "message"),
    (
        ("missing-evidence", "supersedes_evidence_id reference missing IDs"),
        ("evidence-002", "cannot supersede itself"),
    ),
)
def test_evidence_supersession_rejects_missing_and_self_links(
    supersedes_id: str, message: str
) -> None:
    records = representative_records()
    revised = replace(
        records.evidence_assessments[0],
        evidence_id="evidence-002",
        supersedes_evidence_id=supersedes_id,
    )
    payload = records.model_dump(mode="json")
    revised_payload = payload["evidence_assessments"][0].copy()
    revised_payload["evidence_id"] = revised.evidence_id
    revised_payload["supersedes_evidence_id"] = revised.supersedes_evidence_id
    payload["evidence_assessments"].append(revised_payload)

    with pytest.raises(ValidationError, match=message):
        ResearchRecords.model_validate(payload)


def test_evidence_supersession_rejects_cycles() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    original = payload["evidence_assessments"][0]
    original["supersedes_evidence_id"] = "evidence-002"
    revised = original.copy()
    revised["evidence_id"] = "evidence-002"
    revised["supersedes_evidence_id"] = "evidence-001"
    payload["evidence_assessments"].append(revised)

    with pytest.raises(ValidationError, match="supersession cycle"):
        ResearchRecords.model_validate(payload)


def test_evidence_supersession_stays_within_creating_run() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    second_run = payload["research_runs"][0].copy()
    second_run["run_id"] = "other-run"
    payload["research_runs"].append(second_run)
    revised = payload["evidence_assessments"][0].copy()
    revised["evidence_id"] = "evidence-002"
    revised["supersedes_evidence_id"] = "evidence-001"
    revised["record_provenance"] = revised["record_provenance"].copy()
    revised["record_provenance"]["created_in_run_id"] = "other-run"
    payload["evidence_assessments"].append(revised)

    with pytest.raises(ValidationError, match="same research run"):
        ResearchRecords.model_validate(payload)


def test_record_provenance_uses_generic_creation_method() -> None:
    provenance = representative_records().studies[0].record_provenance

    assert provenance.creation_method == "manual"
    assert not hasattr(provenance, "extraction_method")


def test_search_execution_success_and_failure_serialize() -> None:
    payload = representative_records().model_dump(mode="json")["search_executions"]

    assert payload[0]["exact_query"] == '"exact query one"'
    assert payload[0]["provider_result_count"] == 1
    assert payload[2]["status"] == "failed"
    assert payload[2]["error_status_code"] == 429


@pytest.mark.parametrize(
    ("index", "field", "value", "message"),
    (
        (0, "provider_result_count", None, "successful search executions require"),
        (2, "error_type", None, "failed search executions require"),
        (0, "requested_limit", 0, "requested_limit must be positive"),
    ),
)
def test_search_execution_status_metadata_is_validated(
    index: int, field: str, value: str | int | None, message: str
) -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["search_executions"][index][field] = value

    with pytest.raises(ValidationError, match=message):
        ResearchRecords.model_validate(payload)


def test_source_discovery_retains_multi_query_provenance() -> None:
    records = representative_records()
    source_discoveries = [
        discovery for discovery in records.source_discoveries if discovery.source_id == SOURCE_ID
    ]

    assert {discovery.search_execution_id for discovery in source_discoveries} == {
        "search-1",
        "search-2",
    }


def test_discovery_provider_may_differ_from_metadata_provenance() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["sources"][0]["provider_provenance"] = [
        {"provider": "reference-library", "provider_record_id": "source-1"}
    ]

    records = ResearchRecords.model_validate(payload)

    assert records.source_discoveries[0].discovery_record_id == "W1"
    assert records.sources[0].provider_provenance[0].provider == "reference-library"


def test_discovery_record_id_need_not_match_metadata_provenance() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["source_discoveries"][0]["discovery_record_id"] = "different-record"

    records = ResearchRecords.model_validate(payload)

    assert records.source_discoveries[0].discovery_record_id == "different-record"


@pytest.mark.parametrize(
    ("collection", "field", "bad_value"),
    (
        ("search_executions", "run_id", "missing-run"),
        ("source_discoveries", "search_execution_id", "missing-search"),
        ("source_discoveries", "source_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("screening_decisions", "run_id", "missing-run"),
        ("screening_decisions", "source_id", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        ("application_candidates", "linked_evidence_ids", ["missing-evidence"]),
        ("decision_implications", "linked_candidate_ids", ["missing-candidate"]),
    ),
)
def test_new_record_links_cannot_dangle(
    collection: str, field: str, bad_value: str | list[str]
) -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload[collection][0][field] = bad_value

    with pytest.raises(ValidationError, match="reference missing IDs"):
        ResearchRecords.model_validate(payload)


def test_source_discovery_run_must_match_search_execution() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    second_run = payload["research_runs"][0].copy()
    second_run["run_id"] = "other-run"
    payload["research_runs"].append(second_run)
    payload["source_discoveries"][0]["run_id"] = "other-run"

    with pytest.raises(ValidationError, match="must match its SearchExecution run_id"):
        ResearchRecords.model_validate(payload)


def test_study_screening_must_belong_to_source() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["screening_decisions"][2]["source_id"] = str(OTHER_SOURCE_ID)

    with pytest.raises(ValidationError, match="study_id must belong to source_id"):
        ResearchRecords.model_validate(payload)


def test_screening_supersession_is_append_only_and_current_state_is_derived() -> None:
    decisions = representative_records().screening_decisions

    assert {decision.decision_id for decision in current_screening_decisions(decisions)} == {
        "decision-2",
        "decision-3",
    }

    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["screening_decisions"][1]["supersedes_decision_id"] = "missing-decision"
    with pytest.raises(ValidationError, match="supersedes_decision_id reference missing IDs"):
        ResearchRecords.model_validate(payload)


def test_screening_decision_can_only_supersede_same_subject_and_stage() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["screening_decisions"][1]["stage"] = "evidence"

    with pytest.raises(ValidationError, match="same subject and stage"):
        ResearchRecords.model_validate(payload)


def test_duplicate_record_ids_are_rejected() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["search_executions"].append(payload["search_executions"][0])

    with pytest.raises(ValidationError, match="duplicate search execution IDs"):
        ResearchRecords.model_validate(payload)


def test_provenance_run_link_is_validated_for_screening() -> None:
    payload: dict[str, Any] = representative_records().model_dump(mode="json")
    payload["screening_decisions"][0]["record_provenance"]["created_in_run_id"] = "missing-run"

    with pytest.raises(ValidationError, match=r"record_provenance.*reference missing IDs"):
        ResearchRecords.model_validate(payload)


def test_extensible_protocol_references_round_trip_without_application_protocol() -> None:
    records = representative_records()
    restored = ResearchRecords.model_validate_json(records.model_dump_json())

    assert restored.research_runs[0].protocol_references == PROTOCOL_REFERENCES
    assert {reference.protocol_id for reference in PROTOCOL_REFERENCES} == {
        "extraction",
        "screening",
        "evidence-assessment",
    }


def test_export_bundle_rejects_inconsistent_manifest() -> None:
    records = representative_records()
    bad_counts = representative_manifest(records).model_dump(mode="json")
    bad_counts["counts"]["findings"] = 99
    with pytest.raises(ValidationError, match="manifest counts must match records"):
        ExportBundle.model_validate(
            {
                "manifest": bad_counts,
                "run_definitions": representative_bundle(records).run_definitions,
                "records": records,
            }
        )

    bad_runs = representative_manifest(records).model_dump(mode="json")
    bad_runs["contributing_run_ids"] = ["missing-run"]
    with pytest.raises(ValidationError, match="reference missing ResearchRun IDs"):
        ExportBundle.model_validate(
            {
                "manifest": bad_runs,
                "run_definitions": representative_bundle(records).run_definitions,
                "records": records,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("bundle_schema_version", "0.2"), ("records_schema_version", "0.4")),
)
def test_export_manifest_rejects_unsupported_schema_versions(field: str, value: str) -> None:
    payload = representative_manifest(representative_records()).model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        ExportBundleManifest.model_validate(payload)


def test_export_bundle_rejects_run_protocol_mismatch() -> None:
    records = representative_records()
    changed_protocols = (
        replace(PROTOCOL_REFERENCES[0], version="different"),
        *PROTOCOL_REFERENCES[1:],
    )
    mismatched = records.model_copy(
        update={
            "research_runs": (
                replace(records.research_runs[0], protocol_references=changed_protocols),
            )
        }
    )

    with pytest.raises(ValidationError, match="protocol_references must match"):
        representative_bundle(mismatched)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("taxonomy_reference", "different-taxonomy.md"),
        ("taxonomy_version", "different"),
    ),
)
def test_export_bundle_rejects_run_taxonomy_mismatch(field: str, value: str) -> None:
    records = representative_records()
    mismatched_run = replace(records.research_runs[0], **{field: value})
    mismatched = records.model_copy(update={"research_runs": (mismatched_run,)})

    with pytest.raises(ValidationError, match=f"{field} must match bundled RunDefinition"):
        representative_bundle(mismatched)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("definition_schema_version", "different"),
        ("definition_reference", "different.yaml"),
        ("definition_fingerprint", "b" * 64),
    ),
)
def test_export_bundle_rejects_run_definition_identity_mismatch(field: str, value: str) -> None:
    records = representative_records()
    mismatched_run = replace(records.research_runs[0], **{field: value})
    mismatched = records.model_copy(update={"research_runs": (mismatched_run,)})

    with pytest.raises(ValidationError, match=f"{field} must match bundled RunDefinition"):
        representative_bundle(mismatched)


def test_export_bundle_rejects_tampered_run_definition_snapshot() -> None:
    bundle = representative_bundle()
    changed = representative_definition().model_copy(update={"label": "Changed definition"})
    snapshots = (RunDefinitionSnapshot(reference=DEFINITION_REFERENCE, definition=changed),)

    with pytest.raises(ValidationError, match="definition_fingerprint must match bundled"):
        ExportBundle(manifest=bundle.manifest, run_definitions=snapshots, records=bundle.records)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("search_spec_id", "missing-spec"),
        ("provider_id", "different-provider"),
        ("operation_id", "different.operation"),
        ("exact_query", '"different query"'),
        ("parameters", (SearchParameter("filter", "different"),)),
        ("requested_limit", 10),
    ),
)
def test_export_bundle_rejects_search_execution_mismatch(
    field: str, value: str | int | tuple[SearchParameter, ...]
) -> None:
    records = representative_records()
    changed = replace(records.search_executions[2], **{field: value})
    mismatched = records.model_copy(
        update={"search_executions": (*records.search_executions[:2], changed)}
    )

    expected = (
        "references missing SearchSpec" if field == "search_spec_id" else "must match approved"
    )
    with pytest.raises(ValidationError, match=expected):
        representative_bundle(mismatched)


def test_export_bundle_requires_approved_definition() -> None:
    bundle = representative_bundle()
    planned = representative_definition().model_copy(update={"definition_status": "planned"})
    snapshots = (RunDefinitionSnapshot(reference=DEFINITION_REFERENCE, definition=planned),)

    with pytest.raises(ValidationError, match="requires an approved RunDefinition"):
        ExportBundle(manifest=bundle.manifest, run_definitions=snapshots, records=bundle.records)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("stage", "undeclared-stage", "stage 'undeclared-stage' is not declared"),
        ("reason_codes", ("undeclared-reason",), "reason_codes are not declared"),
    ),
)
def test_export_bundle_validates_screening_decisions_against_plan(
    field: str, value: str | tuple[str, ...], message: str
) -> None:
    records = representative_records()
    index = 2 if field == "stage" else 0
    decisions = list(records.screening_decisions)
    decisions[index] = replace(decisions[index], **{field: value})
    mismatched = records.model_copy(update={"screening_decisions": tuple(decisions)})

    with pytest.raises(ValidationError, match=message):
        representative_bundle(mismatched)


def test_frozen_domain_records_have_no_mutable_containers() -> None:
    records = representative_records()
    domain_records = (
        *records.sources,
        *records.studies,
        *records.constructs,
        *records.measurements,
        *records.interventions,
        *records.findings,
        *records.evidence_assessments,
        *records.application_candidates,
        *records.decision_implications,
        *records.research_runs,
        *records.search_executions,
        *records.source_discoveries,
        *records.screening_decisions,
    )
    for record in domain_records:
        for field in fields(record):
            assert not isinstance(getattr(record, field.name), (dict, list))
