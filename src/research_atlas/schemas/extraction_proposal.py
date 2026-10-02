"""Strict bounded proposals; models select passage IDs, never evidence quotations."""

from collections.abc import Collection
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(min_length=1, max_length=20_000, pattern=r"\S")]
DetailKey = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"\S")]
PassageId = Annotated[str, StringConstraints(max_length=12, pattern=r"^p[0-9]{4,}$")]


class ProposalModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ProposedDetail(ProposalModel):
    key: DetailKey
    value: Text


def _unique_details(values: tuple[ProposedDetail, ...]) -> tuple[ProposedDetail, ...]:
    if len({detail.key for detail in values}) != len(values):
        raise ValueError("duplicate scientific detail key")
    return values


Details = Annotated[
    tuple[ProposedDetail, ...], Field(max_length=20), AfterValidator(_unique_details)
]


class ProposedFinding(ProposalModel):
    question_investigated: Text
    outcome_investigated: Text
    result_summary: Text
    direction: Text
    status: Text
    evidence_passage_ids: tuple[PassageId, ...] = Field(min_length=1, max_length=20)
    effect_estimate: Text | None
    uncertainty: Text | None
    moderator_and_subgroup_notes: tuple[Text, ...] = Field(max_length=50)
    author_interpretation: Text | None
    limitations: tuple[Text, ...] = Field(max_length=50)
    details: Details


class ProposedStudy(ProposalModel):
    study_label: Text | None
    study_type: Text | None
    population_summary: Text | None
    domain_summary: Text | None
    setting_summary: Text | None
    sample_summary: Text | None
    details: Details
    findings: tuple[ProposedFinding, ...] = Field(max_length=100)


class ExtractionProposal(ProposalModel):
    studies: tuple[ProposedStudy, ...] = Field(max_length=50)

    def validate_evidence(self, passage_ids: Collection[str]) -> None:
        if not self.studies or any(not study.findings for study in self.studies):
            raise ValueError("no trustworthy empirical findings for every proposed Study")
        if sum(len(study.findings) for study in self.studies) > 200:
            raise ValueError("extraction exceeds total Finding bound")
        for study in self.studies:
            for finding in study.findings:
                if len(set(finding.evidence_passage_ids)) != len(finding.evidence_passage_ids):
                    raise ValueError("duplicate evidence passage ID within Finding")
                for passage_id in finding.evidence_passage_ids:
                    if passage_id not in passage_ids:
                        raise ValueError("unknown evidence passage ID")
