import asyncio
import json
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid7

import pytest
from pydantic import ValidationError

from research_atlas.application.evidence_brief import render_evidence_brief
from research_atlas.application.read_models import (
    EvidenceContext,
    EvidenceCounts,
    FindingEvidence,
    InsightDetail,
    InsightEvidence,
    OutputInsight,
    Page,
    SourceDisplay,
    selected_ids,
)
from research_atlas.application.synthesis import synthesize_insight
from research_atlas.domain.evidence import Insight, InsightFinding
from research_atlas.schemas.insight_proposal import InsightProposal
from tests.persistence.helpers import NOW, document, evidence


def packet() -> FindingEvidence:
    doc = document(uuid7())
    extraction, study, finding = evidence(doc)
    return FindingEvidence(
        finding,
        EvidenceContext(
            study,
            extraction,
            doc,
            SourceDisplay(doc.source_id, None, None, (), None, None, None, ()),
        ),
    )


def proposal(ids: tuple[UUID, ...]) -> dict[str, Any]:
    return {
        "claim": "Available evidence did not demonstrate change",
        "relationships": [
            {
                "finding_id": str(value),
                "relationship": "supporting",
                "rationale": "The reported null result supports this bounded claim",
            }
            for value in ids
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"claim": "  "},
        {"claim": 10},
        {"ontology": {"new": "objects"}},
        {"qualifications": [12]},
        {"relationships": []},
        {"relationships": [{"finding_id": "bad", "relationship": "supporting", "rationale": "x"}]},
        {
            "relationships": [
                {"finding_id": str(uuid7()), "relationship": "supporting", "rationale": " "}
            ]
        },
        {"relationships": [{"finding_id": str(uuid7()), "relationship": "null", "rationale": "x"}]},
    ],
)
def test_external_proposal_is_strict(change: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        InsightProposal.model_validate_json(json.dumps({**proposal((uuid7(),)), **change}))


@pytest.mark.parametrize("mode", ["omitted", "introduced", "duplicate", "unsupported"])
def test_every_selected_finding_must_receive_one_explicit_role(mode: str) -> None:
    ids = (uuid7(), uuid7())
    data = proposal(ids)
    if mode == "omitted":
        data["relationships"].pop()
    elif mode == "introduced":
        data["relationships"][0]["finding_id"] = str(uuid7())
    elif mode == "duplicate":
        data["relationships"][1] = data["relationships"][0]
    else:
        for item in data["relationships"]:
            item["relationship"] = "contextual"
    with pytest.raises(ValueError):
        InsightProposal.model_validate_json(json.dumps(data)).validate_selection(ids)


def test_supplied_synthesizer_receives_exact_packet_and_configuration() -> None:
    item = packet()
    configuration = b"Keep uncertainty and null evidence."
    insight_id = uuid7()
    calls: list[str] = []

    class Publication:
        async def load_evidence(
            self, run_id: str, finding_ids: tuple[UUID, ...]
        ) -> tuple[FindingEvidence, ...]:
            assert run_id == "run" and finding_ids == (item.finding.finding_id,)
            calls.append("load")
            return (item,)

        async def publish(
            self,
            insight: Insight,
            configuration: bytes,
            finding_ids: tuple[UUID, ...],
            relationships: tuple[InsightFinding, ...],
            published_at: datetime,
        ) -> None:
            assert insight.insight_id == insight_id and published_at == NOW
            assert insight.configuration_sha256 == sha256(configuration).hexdigest()
            assert relationships[0].relationship == "supporting"
            assert finding_ids == (item.finding.finding_id,)
            calls.append("publish")

    class Synthesizer:
        async def propose(self, evidence: tuple[FindingEvidence, ...], configuration: bytes) -> str:
            assert evidence == (item,) and configuration.startswith(b"Keep")
            assert evidence[0].finding.direction == "null"
            calls.append("propose")
            return json.dumps(proposal((item.finding.finding_id,)))

    asyncio.run(
        synthesize_insight(
            Publication(),
            Synthesizer(),
            run_id="run",
            insight_id=insight_id,
            finding_ids=(item.finding.finding_id,),
            configuration=configuration,
            provenance=item.finding.record_provenance,
            published_at=NOW,
        )
    )
    assert calls == ["load", "propose", "publish"]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (1, -1), (1, 100001), (True, 0)])
def test_pagination_bounds(limit: int, offset: int) -> None:
    with pytest.raises(ValueError):
        Page(limit, offset)


def test_selection_bounds_and_dependence() -> None:
    for ids in ((), (uuid7(),) * 2, tuple(uuid7() for _ in range(101))):
        with pytest.raises(ValueError):
            selected_ids(ids)
    assert len(EvidenceCounts(3, 1, 1).warnings) == 1
    assert len(EvidenceCounts(3, 2, 2).warnings) == 2
    assert "Independence" in EvidenceCounts(2, 2, 1).warnings[0]


def test_brief_preserves_roles_uncertainty_identity_and_literal_text() -> None:
    item = packet()
    insight = Insight(
        uuid7(),
        "run",
        "No demonstrated change <script>hidden</script>",
        "a" * 64,
        item.finding.record_provenance,
        ("Limited sample",),
        ("Evidence remains uncertain",),
        ("Adults only",),
    )
    links: list[InsightEvidence] = []
    for role in ("supporting", "contradicting", "contextual"):
        finding = replace(item.finding, finding_id=uuid7())
        links.append(
            InsightEvidence(
                InsightFinding(insight.insight_id, finding.finding_id, role, role + " rationale"),
                replace(item, finding=finding),
            )
        )
    output = OutputInsight(
        InsightDetail(insight, "published", NOW, "b" * 64, EvidenceCounts(3, 1, 1)), tuple(links)
    )
    text = render_evidence_brief((output,), title="Evidence Brief", context="Caller context")
    assert text == render_evidence_brief(
        (output,), title="Evidence Brief", context="Caller context"
    )
    for required in (
        "Supporting evidence",
        "Contradictory evidence",
        "Contextual evidence",
        "Evidence remains uncertain",
        "Adults only",
        "Limited sample",
        "not independent studies",
        "3 Findings; 1 distinct Studies; 1 distinct Sources",
        str(item.context.document.document_id),
        str(item.context.extraction.extraction_id),
        "Bibliographic metadata unavailable",
        "&lt;script&gt;",
        "Direction/status: null",
    ):
        assert required in text
    assert "<script>" not in text
    with pytest.raises(ValueError, match="complete"):
        render_evidence_brief((replace(output, evidence=output.evidence[:1]),), title="Partial")
