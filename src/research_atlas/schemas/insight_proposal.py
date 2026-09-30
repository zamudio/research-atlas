"""Small strict boundary for human or probabilistic synthesis output."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Nonblank = Annotated[str, StringConstraints(min_length=1, max_length=20_000, pattern=r"\S")]


class ProposedRelationship(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    finding_id: UUID
    relationship: Literal["supporting", "contradicting", "contextual"]
    rationale: Nonblank


class InsightProposal(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    claim: Nonblank
    qualifications: tuple[Nonblank, ...] = Field(default=(), max_length=100)
    uncertainty_and_limitations: tuple[Nonblank, ...] = Field(default=(), max_length=100)
    generalizability_notes: tuple[Nonblank, ...] = Field(default=(), max_length=100)
    relationships: tuple[ProposedRelationship, ...] = Field(min_length=1, max_length=100)

    def validate_selection(self, selected: tuple[UUID, ...]) -> None:
        ids = tuple(item.finding_id for item in self.relationships)
        if len(ids) != len(set(ids)) or set(ids) != set(selected):
            raise ValueError("proposal must account for every selected Finding exactly once")
        if not any(item.relationship == "supporting" for item in self.relationships):
            raise ValueError("publication requires explicit supporting evidence")
