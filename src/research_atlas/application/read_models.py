"""Bounded, typed product contracts; no database rows or aggregate repositories."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from research_atlas.domain.content import Extraction, SourceDocument
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.evidence import FindingRecord, Insight, InsightFinding
from research_atlas.domain.studies import ExternalIdentifier, StudyRecord

MAX_FINDINGS = 100
MAX_INSIGHTS = 20


def selected_ids(values: tuple[UUID, ...], maximum: int = MAX_FINDINGS) -> tuple[UUID, ...]:
    if not 1 <= len(values) <= maximum or len(set(values)) != len(values):
        raise ValueError(f"select 1..{maximum} distinct IDs")
    return values


@dataclass(frozen=True, slots=True)
class Page:
    limit: int = 20
    offset: int = 0

    def __post_init__(self) -> None:
        if type(self.limit) is not int or type(self.offset) is not int:
            raise ValueError("pagination requires integers")
        if not 1 <= self.limit <= 100 or not 0 <= self.offset <= 100_000:
            raise ValueError("page limit must be 1..100 and offset 0..100000")


@dataclass(frozen=True, slots=True)
class SourceDisplay:
    source_id: UUID
    observation_id: UUID | None
    title: str | None
    credits: tuple[BibliographicCredit, ...]
    year: int | None
    source_type: str | None
    source_url: str | None
    identifiers: tuple[ExternalIdentifier, ...]


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    study: StudyRecord
    extraction: Extraction
    document: SourceDocument
    source: SourceDisplay


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    finding: FindingRecord
    context: EvidenceContext


@dataclass(frozen=True, slots=True)
class StudyContext:
    context: EvidenceContext
    content: bytes


@dataclass(frozen=True, slots=True)
class EvidenceCounts:
    findings: int
    studies: int
    sources: int

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if self.findings > self.studies:
            warnings.append("Multiple Findings share a Study; these are not independent studies.")
        if self.studies > 1 or self.sources > 1:
            warnings.append(
                "Independence across Studies/publications is not established; overlap is possible."
            )
        return tuple(warnings)


@dataclass(frozen=True, slots=True)
class InsightDetail:
    insight: Insight
    publication_status: str
    published_at: datetime | None
    publication_digest: str | None
    evidence: EvidenceCounts


@dataclass(frozen=True, slots=True)
class InsightEvidence:
    relationship: InsightFinding
    evidence: FindingEvidence


@dataclass(frozen=True, slots=True)
class OutputInsight:
    detail: InsightDetail
    evidence: tuple[InsightEvidence, ...]


@dataclass(frozen=True, slots=True)
class SearchProgress:
    provider: str
    status: str
    executions: int
    provider_results: int
    completed_batches: int


@dataclass(frozen=True, slots=True)
class RunProgress:
    run_id: str
    project_id: str
    request: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    searches: tuple[SearchProgress, ...]
    processing: Mapping[str, int]
    screening: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class DiscoveryContext:
    search_execution_id: str
    provider: str
    discovered_at: datetime
    result_position: int


@dataclass(frozen=True, slots=True)
class RunSource:
    source: SourceDisplay
    processing_state: str
    screening_decision: str | None
    screening_detail: Mapping[str, object] | None
    selected_extraction_id: UUID | None
    selected_extraction_status: str | None
    discovery_count: int
    first_discovery: DiscoveryContext | None


@dataclass(frozen=True, slots=True)
class SourceDetail:
    membership: RunSource
    selected_extraction: Extraction | None
    documents: tuple[SourceDocument, ...]
    attempts: tuple[Extraction, ...]
    studies: tuple[StudyRecord, ...]
    findings: tuple[FindingRecord, ...]
