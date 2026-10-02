"""Optional built-in construction; direct StructuredExtractor injection remains supported."""

import httpx

from research_atlas.application.ports.extraction import StructuredExtractor
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from research_atlas.infrastructure.providers.openai_responses import OpenAIResponsesExtractor


def create_structured_extractor(
    settings: ProviderSettings, client: httpx.AsyncClient | None = None
) -> StructuredExtractor:
    provider = settings.extraction_provider
    if provider is None or not provider.strip():
        raise ValueError("extraction provider must be explicitly configured")
    if provider == "ollama":
        return OllamaExtractor(settings, client)
    if provider == "openai":
        return OpenAIResponsesExtractor(settings, client)
    raise ValueError("unknown built-in extraction provider")
