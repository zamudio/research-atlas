"""Explicit compatible Chat endpoint requiring strict JSON-Schema response_format."""

from collections.abc import Mapping

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers._chat_completions import chat_payload, chat_text
from research_atlas.providers._config import (
    model_base_url,
    model_context_capacity,
    model_credential,
    model_name,
    request_fits_context,
)
from research_atlas.providers._http import (
    bearer_headers,
    final_output,
    post_json,
)


class OpenAICompatibleChatModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(
            settings.openai_compatible_api_key,
            "OpenAI-compatible",
            required=False,
        )
        self._base_url = model_base_url(settings, None, api_key=self._key)
        self._timeout = settings.model_timeout_seconds
        self._client = client
        self._context_tokens = model_context_capacity(settings, "openai_compatible")
        self._output_tokens = settings.model_max_output_tokens

    async def fits_context(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bool:
        return request_fits_context(
            chat_payload(self._model, instructions, input_text, schema),
            self._context_tokens,
            self._output_tokens,
            "openai_compatible",
        )

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            chat_payload(self._model, instructions, input_text, schema),
            bearer_headers(self._key),
            self._timeout,
            "openai_compatible",
        )
        return final_output(chat_text(fields, "openai_compatible"), "openai_compatible")
