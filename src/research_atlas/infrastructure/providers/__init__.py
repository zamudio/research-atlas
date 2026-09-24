"""Concrete literature and reference-library adapters."""

from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_atlas.infrastructure.providers.semantic_scholar import (
    SemanticScholarLiteratureSource,
)
from research_atlas.infrastructure.providers.zotero import ZoteroReferenceLibrary

__all__ = [
    "OpenAlexLiteratureSource",
    "SemanticScholarLiteratureSource",
    "ZoteroReferenceLibrary",
]
