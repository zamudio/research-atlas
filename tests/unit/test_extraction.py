import json
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from research_atlas.application.extraction import (
    EXTRACTION_CONTRACT_VERSION,
    EXTRACTION_INSTRUCTIONS,
    extract_source_document,
)
from research_atlas.application.grobid_text import PROJECTION_VERSION, prepare_grobid_text
from research_atlas.application.passage_index import (
    MAX_PASSAGE_CHARACTERS,
    PASSAGE_INDEX_VERSION,
    build_passage_index,
)
from research_atlas.application.ports.extraction import (
    ExtractionEligibilityChanged,
    ExtractionProviderError,
    StructuredExtractionResult,
)
from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.evidence import FindingRecord
from research_atlas.domain.studies import StudyRecord
from research_atlas.schemas.extraction_proposal import ExtractionProposal
from tests.persistence.conftest import run
from tests.persistence.helpers import document

XML = b"""<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><titleStmt><title>Learning study</title></titleStmt></fileDesc>
<profileDesc><abstract><p>We studied learning.</p></abstract></profileDesc></teiHeader>
<text><body><div><head>Results</head><p>The measured outcome <hi>did not</hi> change.
Results remain uncertain.</p></div></body></text></TEI>"""
PASSAGE = "The measured outcome did not change. Results remain uncertain."
PASSAGE_ID = "p0004"


def proposal_bytes(*passage_ids: str) -> bytes:
    return json.dumps(
        {
            "studies": [
                {
                    "study_label": "Study 1",
                    "study_type": "experiment",
                    "sample_summary": "40",
                    "population_summary": None,
                    "domain_summary": None,
                    "setting_summary": None,
                    "details": [],
                    "findings": [
                        {
                            "question_investigated": "Does learning change?",
                            "outcome_investigated": "measured outcome",
                            "result_summary": "No change",
                            "direction": "null",
                            "status": "reported",
                            "evidence_passage_ids": list(passage_ids or (PASSAGE_ID,)),
                            "uncertainty": "Results remain uncertain.",
                            "effect_estimate": None,
                            "moderator_and_subgroup_notes": [],
                            "author_interpretation": None,
                            "limitations": ["small sample"],
                            "details": [{"key": "analysis", "value": "primary"}],
                        }
                    ],
                }
            ]
        },
        indent=2,
    ).encode("utf-8")


def xml_document(content: bytes = XML) -> SourceDocument:
    return replace(document(uuid7(), content), content_kind="grobid_xml")


class FakeProvider:
    def __init__(self, raw: bytes | None = None) -> None:
        self.raw = proposal_bytes() if raw is None else raw
        self.model = "reference:4b"
        self.calls = 0
        self.failure = False
        self.document_text: str | None = None

    @property
    def configuration(self) -> Mapping[str, object]:
        return {"model": self.model, "temperature": 0}

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        self.calls += 1
        self.document_text = document_text
        assert "Source != Study" in instructions
        assert f"[{PASSAGE_ID}] {PASSAGE}" in document_text and "<TEI" not in document_text
        assert "Never copy or paraphrase evidence text" in instructions
        assert "Never invent passage IDs" in instructions
        assert schema["type"] == "object"
        if self.failure:
            raise ExtractionProviderError("transport_failure")
        return StructuredExtractionResult(self.raw, "reference", self.model, "test", "1")


class MemoryPersistence:
    def __init__(self) -> None:
        self.parent = xml_document()
        self.saved: list[tuple[Extraction, bytes, bytes | None]] = []
        self.published: tuple[tuple[StudyRecord, ...], tuple[FindingRecord, ...]] | None = None
        self.prepared: tuple[SourceDocument, bytes] | None = None
        self.reject_publication = False
        self.publication_error: Exception | None = None

    async def load_document(
        self, run_id: str, source_id: UUID, document_id: UUID
    ) -> tuple[SourceDocument, bytes]:
        return self.parent, XML

    async def prepare_document(self, document: SourceDocument, content: bytes) -> UUID:
        self.prepared = document, content
        return document.document_id

    async def record_attempt(
        self, extraction: Extraction, configuration: bytes, raw_output: bytes | None
    ) -> None:
        self.saved.append((extraction, configuration, raw_output))

    async def publish(
        self,
        extraction: Extraction,
        configuration: bytes,
        raw_output: bytes,
        studies: tuple[StudyRecord, ...],
        findings: tuple[FindingRecord, ...],
    ) -> None:
        assert self.saved[-1][2] == raw_output
        if self.reject_publication:
            raise ExtractionEligibilityChanged("eligibility changed")
        if self.publication_error is not None:
            raise self.publication_error
        self.published = studies, findings


def test_namespaced_projection_is_deterministic_useful_and_immutable() -> None:
    parent = xml_document()
    first, content = prepare_grobid_text(parent, XML)
    second, repeated = prepare_grobid_text(parent, XML)
    assert (
        content
        == repeated
        == (
            b"Learning study\n\nWe studied learning.\n\nResults\n\n"
            b"The measured outcome did not change. Results remain uncertain.\n"
        )
    )
    assert first.document_id != second.document_id != parent.document_id
    assert first.content_sha256 == second.content_sha256 == sha256(content).hexdigest()
    assert first.content_kind == "grobid_text"
    assert first.media_type == "text/plain; charset=utf-8"
    assert str(parent.document_id) in first.retrieval_context
    assert PROJECTION_VERSION in first.retrieval_context
    assert parent.content_kind == "grobid_xml" and parent.content_sha256 == sha256(XML).hexdigest()


@pytest.mark.parametrize(
    "content",
    [
        b"<TEI",
        b"<other>text</other>",
        b"<TEI><text><body>text</body></text></TEI>",
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body/></text></TEI>',
        b'<!DOCTYPE TEI [<!ENTITY x "secret">]><TEI>&x;</TEI>',
        b'<!DOCTYPE TEI SYSTEM "http://invalid.test/external"><TEI/>',
        '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE TEI [<!ENTITY x "secret">]>'
        "<TEI>&x;</TEI>".encode("utf-16"),
    ],
)
def test_projection_rejects_unsafe_malformed_and_unusable_xml(content: bytes) -> None:
    with pytest.raises(ValueError):
        prepare_grobid_text(xml_document(content), content)


def test_projection_requires_usable_kind_and_exact_checksum() -> None:
    for parent in (replace(xml_document(), status="failed"), document(uuid7(), XML)):
        with pytest.raises(ValueError, match="usable GROBID"):
            prepare_grobid_text(parent, XML)
    with pytest.raises(ValueError, match="checksum"):
        prepare_grobid_text(xml_document(), XML + b" ")


def test_proposal_selects_passage_ids_without_quotations_locators_or_record_ids() -> None:
    proposal = ExtractionProposal.model_validate_json(proposal_bytes())
    proposal.validate_evidence({PASSAGE_ID})
    assert proposal.studies[0].findings[0].direction == "null"
    assert proposal.studies[0].findings[0].evidence_passage_ids == (PASSAGE_ID,)
    assert PASSAGE.encode() not in proposal_bytes()
    schema_text = json.dumps(ExtractionProposal.model_json_schema())
    assert "evidence_passage_ids" in schema_text
    assert '"passage"' not in schema_text and '"locator"' not in schema_text
    assert "evidence_anchors" not in schema_text
    for raw in (
        b"not JSON",
        b"{}",
        b'{"studies": [{}]}',
        proposal_bytes().replace(b'"study_label"', b'"study_id"'),
        proposal_bytes().replace(b'"evidence_passage_ids":', b'"invented":'),
    ):
        with pytest.raises(ValidationError):
            ExtractionProposal.model_validate_json(raw)
    for extra in (
        {"evidence_anchors": [{"passage": PASSAGE, "locator": "Results"}]},
        {"passage": PASSAGE},
        {"locator": "Results"},
    ):
        data = json.loads(proposal_bytes())
        data["studies"][0]["findings"][0].update(extra)
        with pytest.raises(ValidationError):
            ExtractionProposal.model_validate_json(json.dumps(data))


def test_proposal_scientific_detail_and_total_finding_bounds() -> None:
    raw = json.loads(proposal_bytes())
    raw["studies"][0]["details"] = [{"key": str(i), "value": "detail"} for i in range(21)]
    with pytest.raises(ValidationError):
        ExtractionProposal.model_validate_json(json.dumps(raw))
    raw = json.loads(proposal_bytes())
    study = raw["studies"][0]
    study["findings"] *= 100
    raw["studies"] = [study] * 3
    proposal = ExtractionProposal.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError, match="total Finding bound"):
        proposal.validate_evidence({PASSAGE_ID})


def test_explicit_details_require_unique_keys_and_preserve_empty_study_failure() -> None:
    raw = json.loads(proposal_bytes())
    raw["studies"][0]["details"] = [
        {"key": "design", "value": "experiment"},
        {"key": "design", "value": "duplicate"},
    ]
    with pytest.raises(ValidationError, match="duplicate scientific detail key"):
        ExtractionProposal.model_validate_json(json.dumps(raw))
    raw = json.loads(proposal_bytes())
    raw["studies"][0]["findings"] = []
    proposal = ExtractionProposal.model_validate_json(json.dumps(raw))
    with pytest.raises(ValueError, match="no trustworthy empirical findings"):
        proposal.validate_evidence({PASSAGE_ID})


@pytest.mark.parametrize(
    "raw,status",
    [
        (proposal_bytes(), "accepted"),
        (b"malformed", "failed"),
        (b"{}", "failed"),
        (b'{"studies": []}', "review_needed"),
        (b'{"studies": [{"findings": []}]}', "failed"),
        (proposal_bytes("p9999"), "review_needed"),
        (proposal_bytes(PASSAGE_ID, PASSAGE_ID), "review_needed"),
        (proposal_bytes("fabricated result"), "failed"),
    ],
)
def test_execution_validation_and_exact_raw_retention(raw: bytes, status: str) -> None:
    async def scenario() -> None:
        store = MemoryPersistence()
        provider = FakeProvider(raw)
        result = await extract_source_document(
            store,
            provider,
            run_id="run",
            source_id=store.parent.source_id,
            document_id=store.parent.document_id,
        )
        assert provider.calls == 1 and result.status == status
        assert result.validation_outcome == ("passed" if status == "accepted" else "failed")
        assert result.review_outcome == ("not_required" if status == "accepted" else "pending")
        assert store.prepared is not None
        assert result.source_document_id == store.prepared[0].document_id
        assert sha256(store.saved[0][1]).hexdigest() == result.configuration_sha256
        configuration = json.loads(store.saved[0][1])
        assert configuration["version"] == EXTRACTION_CONTRACT_VERSION == "atlas.extraction.v3"
        assert configuration["projection"] == PROJECTION_VERSION
        assert configuration["passage_index"] == PASSAGE_INDEX_VERSION
        assert configuration["instructions"] == EXTRACTION_INSTRUCTIONS
        assert configuration["schema"] == ExtractionProposal.model_json_schema()
        assert configuration["provider"] == provider.configuration
        reconstructed = build_passage_index(
            store.prepared[1], version=configuration["passage_index"]
        )
        assert reconstructed.model_text == provider.document_text
        legacy = dict(configuration, version="atlas.extraction.v1")
        del legacy["passage_index"]
        legacy_bytes = json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
        assert sha256(legacy_bytes).hexdigest() != result.configuration_sha256
        assert store.saved[1][2] == raw  # response retained before validation/publication
        if status == "accepted":
            assert store.published is not None
            studies, findings = store.published
            assert studies[0].source_id == store.parent.source_id
            assert findings[0].source_study_id == studies[0].study_id
            assert studies[0].extraction_id == result.extraction_id
            assert findings[0].record_provenance == result.record_provenance
            assert findings[0].evidence_anchors[0].passage == PASSAGE
            assert findings[0].evidence_anchors[0].locator == PASSAGE_ID
            assert findings[0].uncertainty == "Results remain uncertain."
            assert findings[0].limitations == ("small sample",)
            assert findings[0].details == {"analysis": "primary"}
            assert PASSAGE.encode() in store.prepared[1]
            assert PASSAGE.encode() not in raw  # Atlas, not the model, supplied the quotation
            assert studies[0].population_summary == ""  # no invented missing information
        else:
            assert store.published is None and store.saved[-1][2] == raw

    run(scenario())


def test_oversized_prepared_block_fails_before_model_io_or_attempt() -> None:
    oversized_xml = XML.replace(b"Results remain uncertain.", b"x" * (MAX_PASSAGE_CHARACTERS + 1))

    class OversizedDocument(MemoryPersistence):
        async def load_document(
            self, run_id: str, source_id: UUID, document_id: UUID
        ) -> tuple[SourceDocument, bytes]:
            return xml_document(oversized_xml), oversized_xml

    async def scenario() -> None:
        store = OversizedDocument()
        provider = FakeProvider()
        with pytest.raises(ValueError, match="passage bound"):
            await extract_source_document(
                store,
                provider,
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert provider.calls == 0 and not store.saved and store.published is None
        assert store.prepared is None

    run(scenario())


@pytest.mark.parametrize("passage_ids", [(), (PASSAGE_ID,) * 21, ("p4",), ("P0004",)])
def test_proposal_bounds_and_formats_passage_ids(passage_ids: tuple[str, ...]) -> None:
    raw = json.loads(proposal_bytes())
    raw["studies"][0]["findings"][0]["evidence_passage_ids"] = passage_ids
    with pytest.raises(ValidationError):
        ExtractionProposal.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "passage_ids,message",
    [(("p9999",), "unknown"), ((PASSAGE_ID, PASSAGE_ID), "duplicate")],
)
def test_proposal_rejects_unknown_and_duplicate_ids(
    passage_ids: tuple[str, ...], message: str
) -> None:
    proposal = ExtractionProposal.model_validate_json(proposal_bytes(*passage_ids))
    with pytest.raises(ValueError, match=message):
        proposal.validate_evidence({PASSAGE_ID})


def test_multiple_supporting_passages_resolve_in_model_selected_order() -> None:
    async def scenario() -> None:
        store = MemoryPersistence()
        result = await extract_source_document(
            store,
            FakeProvider(proposal_bytes(PASSAGE_ID, "p0003")),
            run_id="run",
            source_id=store.parent.source_id,
            document_id=store.parent.document_id,
        )
        assert result.status == "accepted" and store.published is not None
        assert store.prepared is not None
        anchors = store.published[1][0].evidence_anchors
        assert tuple((anchor.locator, anchor.passage) for anchor in anchors) == (
            (PASSAGE_ID, PASSAGE),
            ("p0003", "Results"),
        )
        assert all(
            anchor.passage is not None and anchor.passage.encode() in store.prepared[1]
            for anchor in anchors
        )

    run(scenario())


def test_provider_failure_publication_rejection_and_configuration_identity() -> None:
    async def scenario() -> None:
        identities: list[str] = []
        for failure, reject, model in [(True, False, "a"), (False, True, "a"), (False, False, "b")]:
            store = MemoryPersistence()
            store.reject_publication = reject
            provider = FakeProvider()
            provider.failure, provider.model = failure, model
            result = await extract_source_document(
                store,
                provider,
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
            identities.append(result.configuration_sha256)
            assert result.status == (
                "failed" if failure else "review_needed" if reject else "accepted"
            )
            if failure:
                assert result.validation_outcome == "pending" and result.review_outcome == "pending"
                assert store.saved[-1][2] is None
            if reject:
                assert result.validation_outcome == "passed" and result.review_outcome == "pending"
                assert store.saved[-1][2] == provider.raw and store.published is None
        assert identities[0] == identities[1] != identities[2]

    run(scenario())


def test_returned_bytes_survive_provider_identity_failure() -> None:
    class FailedProvider(FakeProvider):
        async def extract(
            self, instructions: str, document_text: str, schema: Mapping[str, object]
        ) -> StructuredExtractionResult:
            raise ExtractionProviderError("identity_mismatch", raw_output=self.raw)

    async def scenario() -> None:
        store = MemoryPersistence()
        provider = FailedProvider()
        result = await extract_source_document(
            store,
            provider,
            run_id="run",
            source_id=store.parent.source_id,
            document_id=store.parent.document_id,
        )
        assert result.status == "failed" and store.saved[-1][2] == provider.raw
        assert result.validation_outcome == "pending" and result.review_outcome == "pending"
        assert store.published is None

    run(scenario())


@pytest.mark.parametrize(
    "error",
    [
        ValueError("publication invariant"),
        RuntimeError("unexpected"),
        IntegrityError("publication", {}, RuntimeError("database failure")),
    ],
)
def test_unexpected_publication_errors_propagate_without_relabeling(error: Exception) -> None:
    async def scenario() -> None:
        store = MemoryPersistence()
        store.publication_error = error
        provider = FakeProvider()
        with pytest.raises(type(error)) as raised:
            await extract_source_document(
                store,
                provider,
                run_id="run",
                source_id=store.parent.source_id,
                document_id=store.parent.document_id,
            )
        assert raised.value is error
        assert store.saved[-1][0].status == "running" and store.saved[-1][2] == provider.raw
        assert store.published is None

    run(scenario())


def test_separate_studies_have_atlas_owned_findings_and_ids() -> None:
    async def scenario() -> None:
        raw = json.loads(proposal_bytes())
        raw["studies"] *= 2
        store = MemoryPersistence()
        result = await extract_source_document(
            store,
            FakeProvider(json.dumps(raw).encode()),
            run_id="run",
            source_id=store.parent.source_id,
            document_id=store.parent.document_id,
        )
        assert result.status == "accepted" and store.published is not None
        studies, findings = store.published
        assert len({study.study_id for study in studies}) == 2
        assert len({finding.finding_id for finding in findings}) == 2
        assert [finding.source_study_id for finding in findings] == [
            study.study_id for study in studies
        ]

    run(scenario())
