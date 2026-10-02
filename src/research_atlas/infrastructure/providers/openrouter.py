"""Native OpenRouter endpoint with schema-aware routing and no provider fallbacks."""

from collections.abc import Mapping

import httpx

from research_atlas.application.ports.extraction import StructuredExtractionResult
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers._chat_completions import chat_payload, chat_text
from research_atlas.infrastructure.providers._extraction_config import (
    extraction_base_url,
    extraction_credential,
    extraction_model,
)
from research_atlas.infrastructure.providers._extraction_http import (
    bearer_headers,
    extraction_result,
    post_json,
)

_VERSION = "atlas.openrouter-chat.v1"


class OpenRouterExtractor:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._key = extraction_credential(settings.openrouter_api_key, "OpenRouter")
        self._base_url = extraction_base_url(
            settings, "https://openrouter.ai/api/v1", api_key=self._key
        )
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _VERSION,
            "provider": "openrouter",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_name": "atlas_extraction",
            "strict": True,
            "stream": False,
            "require_parameters": True,
            "allow_fallbacks": False,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        payload = chat_payload(self._model, instructions, document_text, schema)
        payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            payload,
            bearer_headers(self._key),
            self._timeout,
            "openrouter",
        )
        return extraction_result(
            chat_text(fields, "openrouter"),
            fields.get("model"),
            "openrouter",
            "atlas-openrouter-chat",
            _VERSION,
            self._key,
        )
