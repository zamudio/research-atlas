"""Paper-level citation metadata and question-relevant, grounded evidence."""

import re
from dataclasses import dataclass


def normalize_openalex_id(value: str) -> str:
    value = re.sub(r"^https?://openalex\.org/", "", value.strip(), flags=re.IGNORECASE)
    value = value.rstrip("/").upper()
    if not re.fullmatch(r"W[1-9][0-9]*", value):
        raise ValueError("invalid OpenAlex work ID")
    return value


def normalize_doi(value: str) -> str:
    value = re.sub(
        r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.IGNORECASE
    ).lower()
    if not re.fullmatch(r"10\.[0-9]{4,9}/\S+", value):
        raise ValueError("invalid DOI")
    return value


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    authors: tuple[str, ...]
    year: int | None
    openalex_id: str
    doi: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "openalex_id", normalize_openalex_id(self.openalex_id))
        if self.doi is not None:
            object.__setattr__(self, "doi", normalize_doi(self.doi))

    @property
    def key(self) -> str:
        return self.openalex_id


@dataclass(frozen=True, slots=True)
class Evidence:
    summary: str
    passages: tuple[str, ...]
    context: str | None
    limitations: str | None


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    source: Source
    content_sha256: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True, slots=True)
class EvidenceReview:
    question: str
    reviewed_sources: int
    sources: tuple[SourceEvidence, ...]
