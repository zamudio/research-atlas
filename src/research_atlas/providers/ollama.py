"""Ollama reference adapter; one generation, no reasoning retention."""

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers import (
    ModelProviderError,
)
from research_atlas.providers._config import (
    model_base_url,
    model_name,
)


class OllamaModel:
    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        key = settings.ollama_api_key
        self._api_key = key if key is not None and key.get_secret_value().strip() else None
        self._base_url = model_base_url(settings, "http://localhost:11434", api_key=self._api_key)
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
            "stream": False,
            "think": False,
            "format": dict(schema),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "options": {"temperature": 0},
        }
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.post(
                    self._base_url + "/api/chat",
                    json=payload,
                    headers=(
                        {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
                        if self._api_key is not None
                        else {}
                    ),
                    timeout=self._timeout,
                    follow_redirects=False,
                )
        except httpx.HTTPError, TimeoutError:
            raise ModelProviderError("ollama_transport_failure") from None
        if not response.is_success:
            raise ModelProviderError("ollama_http_failure")
        try:
            envelope: object = response.json()
            if not isinstance(envelope, dict):
                raise ValueError
            fields = cast(dict[str, object], envelope)
            message: object = fields.get("message")
            if not isinstance(message, dict):
                raise ValueError
            content: object = cast(dict[str, object], message).get("content")
            model: object = fields.get("model")
            if not isinstance(content, str):
                raise ValueError
            raw = content.encode("utf-8")
        except ValueError, UnicodeError:
            raise ModelProviderError("ollama_malformed_envelope") from None
        if fields.get("done") is not True or (
            "done_reason" in fields and fields["done_reason"] != "stop"
        ):
            raise ModelProviderError("ollama_incomplete_completion")
        if not content.strip():
            raise ModelProviderError("ollama_empty_content")
        if not isinstance(model, str) or model != self._model:
            raise ModelProviderError("ollama_model_identity_mismatch")
        return raw
