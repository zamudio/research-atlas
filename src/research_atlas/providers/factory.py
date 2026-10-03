"""Optional built-in construction; direct StructuredModel injection remains supported."""

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers import StructuredModel
from research_atlas.providers.anthropic import AnthropicModel
from research_atlas.providers.deepseek_responses import DeepSeekResponsesModel
from research_atlas.providers.gemini import GeminiInteractionsModel
from research_atlas.providers.kimi import KimiModel
from research_atlas.providers.ollama import OllamaModel
from research_atlas.providers.openai_compatible_chat import (
    OpenAICompatibleChatModel,
)
from research_atlas.providers.openai_responses import OpenAIResponsesModel
from research_atlas.providers.openrouter import OpenRouterModel


def create_structured_model(
    settings: ProviderSettings, client: httpx.AsyncClient | None = None
) -> StructuredModel:
    provider = settings.model_provider
    if provider is None or not provider.strip():
        raise ValueError("model provider must be explicitly configured")
    if provider == "ollama":
        return OllamaModel(settings, client)
    if provider == "openai":
        return OpenAIResponsesModel(settings, client)
    if provider == "anthropic":
        return AnthropicModel(settings, client)
    if provider == "gemini":
        return GeminiInteractionsModel(settings, client)
    if provider == "kimi":
        return KimiModel(settings, client)
    if provider == "openrouter":
        return OpenRouterModel(settings, client)
    if provider == "deepseek":
        return DeepSeekResponsesModel(settings, client)
    if provider == "openai_compatible":
        return OpenAICompatibleChatModel(settings, client)
    raise ValueError("unknown built-in model provider")
