"""Concrete literature and reference-library adapters."""

from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_atlas.infrastructure.providers.semantic_scholar import (
    SemanticScholarBulkSearch,
    SemanticScholarRelevanceSearch,
)
from research_atlas.infrastructure.providers.zotero import ZoteroReferenceLibrary

__all__ = [
    "OpenAlexLiteratureSource",
    "SemanticScholarBulkSearch",
    "SemanticScholarRelevanceSearch",
    "ZoteroReferenceLibrary",
]
