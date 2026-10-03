"""OpenAI Responses reference adapter using httpx and stateless strict output."""

from collections.abc import Mapping

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers import (
    ModelProviderError,
)
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
from research_atlas.providers._responses import response_text

_SCHEMA_NAME = "atlas_output"


class OpenAIResponsesModel:
    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._api_key = model_credential(settings.openai_api_key, "OpenAI")
        self._base_url = model_base_url(
            settings, "https://api.openai.com/v1", api_key=self._api_key
        )
        self._timeout = settings.model_timeout_seconds
        self._client = client

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        if self._client is not None:
            return await self._generate(self._client, instructions, input_text, schema)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._generate(client, instructions, input_text, schema)

    async def _generate(
        self,
        client: httpx.AsyncClient,
        instructions: str,
        input_text: str,
        schema: Mapping[str, object],
    ) -> bytes:
        payload = {
            "model": self._model,
            "instructions": instructions,
            "input": input_text,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _SCHEMA_NAME,
                    "strict": True,
                    "schema": dict(schema),
                }
            },
        }
        fields = await post_json(
            client,
            self._base_url + "/responses",
            payload,
            bearer_headers(self._api_key),
            self._timeout,
            "openai",
        )
        try:
            status = fields.get("status")
            if status not in (
                "completed",
                "incomplete",
                "failed",
                "cancelled",
                "queued",
                "in_progress",
            ):
                raise ValueError
            raw, refused, message_incomplete = response_text(fields)
        except ValueError, TypeError, UnicodeError:
            raise ModelProviderError("openai_malformed_envelope") from None
        if refused:
            raise ModelProviderError("openai_refusal")
        if status in {"failed", "cancelled"} or fields.get("error") is not None:
            raise ModelProviderError("openai_failed_response")
        if (
            status != "completed"
            or message_incomplete
            or fields.get("incomplete_details") is not None
        ):
            raise ModelProviderError("openai_incomplete_response")
        return final_output(raw, "openai")
