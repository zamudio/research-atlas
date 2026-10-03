import asyncio
import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, asdict
from hashlib import sha256

import pytest
from pydantic import ValidationError

from research_atlas import Source, extract_evidence
from research_atlas.extraction import EXTRACTION_INSTRUCTIONS, ExtractionProposal

SOURCE = Source("Learning", ("First Author", "Second Author"), 2024, "W123")
PASSAGE = "Response time predicted later recall in Experiment 2."
OTHER = "Confidence judgments were poorly calibrated in this sample."
XML = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    f"<p>{PASSAGE}</p><p>{OTHER}</p></body></text></TEI>"
).encode()


def proposal_bytes(ids: tuple[str, ...] = ("p0001",)) -> bytes:
    return json.dumps(
        {
            "evidence": [
                {
                    "summary": "Response time predicted recall.",
                    "context": "Experiment 2",
                    "limitations": None,
                    "evidence_passage_ids": ids,
                }
            ]
        }
    ).encode()


class FakeModel:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.calls = 0

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        self.calls += 1
        return self.raw


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("  What does response time tell us?\n", PASSAGE),
        ("What does confidence tell us?", OTHER),
        ("What affects ocean temperatures?", None),
    ],
)
def test_question_controls_relevance_and_is_preserved_exactly(
    question: str, expected: str | None
) -> None:
    class QuestionModel:
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert instructions == EXTRACTION_INSTRUCTIONS + "\nResearch question:\n" + question
            assert input_text == f"[p0001] {PASSAGE}\n\n[p0002] {OTHER}\n"
            assert schema == ExtractionProposal.model_json_schema()
            supplied_question = instructions.split("\nResearch question:\n", 1)[1]
            if "response time" in supplied_question:
                return proposal_bytes()
            if "confidence" in supplied_question:
                return json.dumps(
                    {
                        "evidence": [
                            {
                                "summary": "Confidence was poorly calibrated.",
                                "context": "This sample",
                                "limitations": None,
                                "evidence_passage_ids": ["p0002"],
                            }
                        ]
                    }
                ).encode()
            return b'{"evidence": []}'

    result = asyncio.run(
        extract_evidence(question=question, source=SOURCE, content=XML, model=QuestionModel())
    )
    assert tuple(p for e in result.evidence for p in e.passages) == (
        (expected,) if expected is not None else ()
    )
    assert result.content_sha256 == sha256(XML).hexdigest()
    assert result.source is SOURCE


def test_exact_grounding_multiple_items_without_independent_identity() -> None:
    raw = json.loads(proposal_bytes())
    raw["evidence"].append(
        {
            "summary": "Confidence was poorly calibrated.",
            "context": None,
            "limitations": "Limited to this sample.",
            "evidence_passage_ids": ["p0002"],
        }
    )
    result = asyncio.run(
        extract_evidence(
            question="What do these signals tell us?",
            source=SOURCE,
            content=XML,
            model=FakeModel(json.dumps(raw).encode()),
        )
    )
    assert [item.passages for item in result.evidence] == [(PASSAGE,), (OTHER,)]
    assert set(asdict(result)) == {"source", "content_sha256", "evidence"}
    assert all(
        set(asdict(item)) == {"summary", "passages", "context", "limitations"}
        for item in result.evidence
    )
    assert "p0001" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.evidence[0].summary = "changed"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("ids", [("p9999",), ("p0001", "p0001"), (), ("invented",)])
def test_invalid_grounding_fails(ids: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        asyncio.run(
            extract_evidence(
                question="What helps learning?",
                source=SOURCE,
                content=XML,
                model=FakeModel(proposal_bytes(ids)),
            )
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", ""),
        ("summary", " \n"),
        ("summary", 123),
        ("summary", "x" * 4001),
        ("context", False),
        ("limitations", []),
        ("passages", ["Invented quotation"]),
        ("evidence_passage_ids", "p0001"),
    ],
)
def test_canonical_schema_rejects_invalid_fields_and_model_quotations(
    field: str, value: object
) -> None:
    raw = json.loads(proposal_bytes())
    raw["evidence"][0][field] = value
    with pytest.raises(ValidationError):
        asyncio.run(
            extract_evidence(
                question="Question?",
                source=SOURCE,
                content=XML,
                model=FakeModel(json.dumps(raw).encode()),
            )
        )


@pytest.mark.parametrize("raw", [b"{}", b'{"evidence":[],"extra":true}', b"[]", b"not json"])
def test_invalid_top_level_output_fails(raw: bytes) -> None:
    with pytest.raises(ValidationError):
        asyncio.run(
            extract_evidence(
                question="Question?",
                source=SOURCE,
                content=XML,
                model=FakeModel(raw),
            )
        )


@pytest.mark.parametrize("question", ["", " \t\n", "x" * 8001])
def test_question_validation_precedes_model_call(question: str) -> None:
    model = FakeModel(b'{"evidence": []}')
    with pytest.raises(ValueError, match="question"):
        asyncio.run(extract_evidence(question=question, source=SOURCE, content=XML, model=model))
    assert model.calls == 0
