"""Optional built-in construction; direct StructuredExtractor injection remains supported."""

import httpx

from research_atlas.application.ports.extraction import StructuredExtractor
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.anthropic import AnthropicExtractor
from research_atlas.infrastructure.providers.deepseek_responses import DeepSeekResponsesExtractor
from research_atlas.infrastructure.providers.gemini import GeminiInteractionsExtractor
from research_atlas.infrastructure.providers.kimi import KimiExtractor
from research_atlas.infrastructure.providers.ollama import OllamaExtractor
from research_atlas.infrastructure.providers.openai_compatible_chat import (
    OpenAICompatibleChatExtractor,
)
from research_atlas.infrastructure.providers.openai_responses import OpenAIResponsesExtractor
from research_atlas.infrastructure.providers.openrouter import OpenRouterExtractor


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
    if provider == "anthropic":
        return AnthropicExtractor(settings, client)
    if provider == "gemini":
        return GeminiInteractionsExtractor(settings, client)
    if provider == "kimi":
        return KimiExtractor(settings, client)
    if provider == "openrouter":
        return OpenRouterExtractor(settings, client)
    if provider == "deepseek":
        return DeepSeekResponsesExtractor(settings, client)
    if provider == "openai_compatible":
        return OpenAICompatibleChatExtractor(settings, client)
    raise ValueError("unknown built-in extraction provider")
