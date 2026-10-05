"""Small typed contracts for acquired full text and ranked source passages."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ContentSource(BaseModel):
    kind: Literal["grobid_xml", "oa_pdf", "openalex_pdf"]
    url: str


class Work(BaseModel):
    openalex_id: str
    title: str
    doi: str | None = None
    year: int | None = None
    # Acquisition input is omitted from JSON; source records the successful route.
    routes: tuple[ContentSource, ...] = Field(default=(), exclude=True, repr=False)

    @field_validator("openalex_id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        value = re.sub(r"^https?://openalex\.org/", "", value.strip(), flags=re.IGNORECASE)
        value = value.rstrip("/").upper()
        if not re.fullmatch(r"W[1-9][0-9]*", value):
            raise ValueError("invalid OpenAlex work ID")
        return value


class Passage(BaseModel):
    passage_id: str
    section: str | None
    text: str


class Document(BaseModel):
    work: Work
    source: ContentSource
    passages: tuple[Passage, ...]


class Evidence(BaseModel):
    passage_id: str
    section: str | None
    text: str
    score: float = Field(ge=0, allow_inf_nan=False)


class PaperEvidence(BaseModel):
    work: Work
    source: ContentSource
    evidence: tuple[Evidence, ...]


class Failure(BaseModel):
    openalex_id: str | None
    stage: Literal["discovery", "acquisition", "preparation"]
    reason: str


class EvidenceResult(BaseModel):
    question: str
    papers: tuple[PaperEvidence, ...]
    failures: tuple[Failure, ...]
