"""Strict and bounded probabilistic output; model supplies no Atlas identifiers."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(min_length=1, max_length=20_000, pattern=r"\S")]
DetailKey = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"\S")]
Details = Annotated[dict[DetailKey, Text], Field(max_length=20)]


class ProposalModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ProposedAnchor(ProposalModel):
    passage: Text
    locator: Text | None = None


class ProposedFinding(ProposalModel):
    question_investigated: Text
    outcome_investigated: Text
    result_summary: Text
    direction: Text
    status: Text
    evidence_anchors: tuple[ProposedAnchor, ...] = Field(min_length=1, max_length=20)
    effect_estimate: Text | None = None
    uncertainty: Text | None = None
    moderator_and_subgroup_notes: tuple[Text, ...] = Field(default=(), max_length=50)
    author_interpretation: Text | None = None
    limitations: tuple[Text, ...] = Field(default=(), max_length=50)
    details: Details = Field(default_factory=dict)


class ProposedStudy(ProposalModel):
    study_label: Text | None = None
    study_type: Text | None = None
    population_summary: Text | None = None
    domain_summary: Text | None = None
    setting_summary: Text | None = None
    sample_summary: Text | None = None
    details: Details = Field(default_factory=dict)
    findings: tuple[ProposedFinding, ...] = Field(max_length=100)


class ExtractionProposal(ProposalModel):
    studies: tuple[ProposedStudy, ...] = Field(max_length=50)

    def validate_evidence(self, content: bytes) -> None:
        if not self.studies or any(not study.findings for study in self.studies):
            raise ValueError("no trustworthy empirical findings for every proposed Study")
        if sum(len(study.findings) for study in self.studies) > 200:
            raise ValueError("extraction exceeds total Finding bound")
        for study in self.studies:
            for finding in study.findings:
                for anchor in finding.evidence_anchors:
                    if anchor.passage.encode("utf-8") not in content:
                        raise ValueError("evidence passage does not occur in prepared document")
