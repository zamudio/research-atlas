"""Supported scholarly metadata discovery adapters."""

from research_atlas.infrastructure.providers.crossref import CrossrefWorksSearch
from research_atlas.infrastructure.providers.openalex import (
    OpenAlexLiteratureSource,
    OpenAlexSemanticSearch,
)

__all__ = ["CrossrefWorksSearch", "OpenAlexLiteratureSource", "OpenAlexSemanticSearch"]
