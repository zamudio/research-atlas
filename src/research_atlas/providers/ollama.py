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
from research_atlas.providers._http import bearer_headers, object_fields, post_json


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
        self._context_override = settings.model_context_tokens
        self._advertised_context: int | None = None

    async def _context_tokens(self, client: httpx.AsyncClient) -> int:
        if self._advertised_context is None:
            fields = await post_json(
                client,
                self._base_url + "/api/show",
                {"model": self._model},
                bearer_headers(self._api_key),
                self._timeout,
                "ollama",
            )
            try:
                info = object_fields(fields.get("model_info"))
                # Ollama uses architecture-specific keys such as llama.context_length.
                contexts = [
                    (key, value) for key, value in info.items() if key.endswith(".context_length")
                ]
                if len(contexts) != 1:
                    raise ValueError
                key, context = contexts[0]
                if key == ".context_length" or type(context) is not int or context <= 0:
                    raise ValueError
            except ValueError:
                raise ModelProviderError("ollama_invalid_context_metadata") from None
            self._advertised_context = context
        if self._context_override is not None:
            if self._context_override > self._advertised_context:
                raise ModelProviderError("ollama_context_override_exceeds_maximum")
            return self._context_override
        return self._advertised_context

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
        context_tokens = await self._context_tokens(client)
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "format": dict(schema),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "options": {"temperature": 0, "num_ctx": context_tokens},
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
