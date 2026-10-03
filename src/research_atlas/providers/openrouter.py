"""Native OpenRouter endpoint with schema-aware routing and no provider fallbacks."""

from collections.abc import Mapping

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers._chat_completions import chat_payload, chat_text
from research_atlas.providers._config import (
    model_base_url,
    model_credential,
    model_name,
)
from research_atlas.providers._http import (
    bearer_headers,
    final_output,
    post_json,
)


class OpenRouterModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(settings.openrouter_api_key, "OpenRouter")
        self._base_url = model_base_url(settings, "https://openrouter.ai/api/v1", api_key=self._key)
        self._timeout = settings.model_timeout_seconds
        self._client = client

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        payload = chat_payload(self._model, instructions, input_text, schema)
        payload["provider"] = {"require_parameters": True, "allow_fallbacks": False}
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            payload,
            bearer_headers(self._key),
            self._timeout,
            "openrouter",
        )
        return final_output(chat_text(fields, "openrouter"), "openrouter")
