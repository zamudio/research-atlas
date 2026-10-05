"""Native stateless DeepSeek Responses; no JSON-mode downgrade or provider fallback."""

from collections.abc import Mapping
from typing import cast

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers import (
    ModelProviderError,
)
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
from research_atlas.providers._responses import response_text


class DeepSeekResponsesModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(settings.deepseek_api_key, "DeepSeek")
        self._base_url = model_base_url(settings, "https://api.deepseek.com", api_key=self._key)
        self._timeout = settings.model_timeout_seconds
        self._client = client
        self._context_tokens = model_context_capacity(settings, "deepseek")
        self._output_tokens = settings.model_max_output_tokens

    def _payload(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> dict[str, object]:
        return {
            "model": self._model,
            "instructions": instructions,
            "input": input_text,
            "stream": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "atlas_output",
                    "schema": dict(schema),
                }
            },
        }

    async def fits_context(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bool:
        return request_fits_context(
            self._payload(instructions, input_text, schema),
            self._context_tokens,
            self._output_tokens,
            "deepseek",
        )

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        # DeepSeek is stateless by contract. store is unsupported; do not depend on it.
        # Its documented text.format has no strict switch: json_schema enforces the schema.
        fields = await post_json(
            self._client,
            self._base_url + "/responses",
            self._payload(instructions, input_text, schema),
            bearer_headers(self._key),
            self._timeout,
            "deepseek",
        )
        try:
            status = fields.get("status")
            if status not in ("completed", "incomplete", "failed", "in_progress"):
                raise ValueError
            raw, refused, message_incomplete = response_text(fields)
        except ValueError, TypeError, UnicodeError:
            raise ModelProviderError("deepseek_malformed_envelope") from None
        if refused:
            raise ModelProviderError("deepseek_refusal")
        details = fields.get("incomplete_details")
        if (
            isinstance(details, dict)
            and cast(dict[str, object], details).get("reason") == "content_filter"
        ):
            raise ModelProviderError("deepseek_refusal")
        if status == "failed" or fields.get("error") is not None:
            raise ModelProviderError("deepseek_failed_response")
        if status != "completed" or message_incomplete or details is not None:
            raise ModelProviderError("deepseek_incomplete_response")
        return final_output(raw, "deepseek")
