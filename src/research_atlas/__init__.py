"""In-memory scholarly search and question-relevant evidence extraction."""

from research_atlas.extraction import extract_evidence
from research_atlas.models import Evidence, EvidenceReview, Source, SourceEvidence
from research_atlas.research import collect_evidence

__all__ = [
    "Evidence",
    "EvidenceReview",
    "Source",
    "SourceEvidence",
    "collect_evidence",
    "extract_evidence",
]
