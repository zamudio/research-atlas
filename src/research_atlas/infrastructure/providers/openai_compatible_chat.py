"""Explicit compatible Chat endpoint requiring strict JSON-Schema response_format."""

from collections.abc import Mapping

import httpx

from research_atlas.application.ports.extraction import StructuredExtractionResult
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers._chat_completions import chat_payload, chat_text
from research_atlas.infrastructure.providers._extraction_config import (
    extraction_base_url,
    extraction_credential,
    extraction_model,
    preferred_credential,
)
from research_atlas.infrastructure.providers._extraction_http import (
    bearer_headers,
    extraction_result,
    post_json,
)

_VERSION = "atlas.openai-compatible-chat.v1"


class OpenAICompatibleChatExtractor:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._key = extraction_credential(
            preferred_credential(settings.openai_compatible_api_key, settings.extraction_api_key),
            "OpenAI-compatible",
            required=False,
        )
        self._base_url = extraction_base_url(settings, None, api_key=self._key)
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _VERSION,
            "provider": "openai_compatible",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_name": "atlas_extraction",
            "strict": True,
            "stream": False,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            chat_payload(self._model, instructions, document_text, schema),
            bearer_headers(self._key),
            self._timeout,
            "openai_compatible",
        )
        return extraction_result(
            chat_text(fields, "openai_compatible"),
            fields.get("model"),
            "openai_compatible",
            "atlas-openai-compatible-chat",
            _VERSION,
            self._key,
        )
