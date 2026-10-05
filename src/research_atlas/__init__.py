"""A bounded scholarly-evidence pipeline, with no model service required."""

from research_atlas.models import ContentSource, Document, Evidence, EvidenceResult, Failure, Work
from research_atlas.pipeline import evidence

__all__ = ["ContentSource", "Document", "Evidence", "EvidenceResult", "Failure", "Work", "evidence"]
