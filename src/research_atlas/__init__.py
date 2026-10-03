"""In-memory scholarly search and question-relevant evidence extraction."""

from research_atlas.extraction import extract_evidence
from research_atlas.models import Evidence, Source, SourceEvidence

__all__ = ["Evidence", "Source", "SourceEvidence", "extract_evidence"]
