"""Concrete literature and reference-library adapters."""

from research_workbench.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_workbench.infrastructure.providers.semantic_scholar import (
    SemanticScholarLiteratureSource,
)
from research_workbench.infrastructure.providers.zotero import ZoteroReferenceLibrary

__all__ = [
    "OpenAlexLiteratureSource",
    "SemanticScholarLiteratureSource",
    "ZoteroReferenceLibrary",
]
