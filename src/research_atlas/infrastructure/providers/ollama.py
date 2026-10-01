"""Disposable local reference adapter; one generation, no reasoning retention."""

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx

from research_atlas.application.ports.extraction import (
    ExtractionProviderError,
    StructuredExtractionResult,
)
from research_atlas.infrastructure.config import ProviderSettings

_ADAPTER_VERSION = "atlas.ollama-chat.v1"


class OllamaExtractor:
    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self._base_url = settings.ollama_base_url.rstrip("/")
        url = httpx.URL(self._base_url)
        if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query:
            raise ValueError("Ollama base URL requires HTTP(S) without credentials or query")
        self._model = settings.extraction_model
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _ADAPTER_VERSION,
            "base_url": self._base_url,
            "model": self._model,
            "stream": False,
            "think": False,
            "temperature": 0,
            "timeout_seconds": self._timeout,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        if self._client is not None:
            return await self._extract(self._client, instructions, document_text, schema)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._extract(client, instructions, document_text, schema)

    async def _extract(
        self,
        client: httpx.AsyncClient,
        instructions: str,
        document_text: str,
        schema: Mapping[str, object],
    ) -> StructuredExtractionResult:
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "format": dict(schema),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": document_text},
            ],
            "options": {"temperature": 0},
        }
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.post(
                    self._base_url + "/api/chat",
                    json=payload,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
        except httpx.HTTPError, TimeoutError:
            raise ExtractionProviderError("ollama_transport_failure") from None
        if not response.is_success:
            raise ExtractionProviderError("ollama_http_failure")
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
            raise ExtractionProviderError("ollama_malformed_envelope") from None
        if fields.get("done") is not True or (
            "done_reason" in fields and fields["done_reason"] != "stop"
        ):
            raise ExtractionProviderError("ollama_incomplete_completion", raw_output=raw)
        if not content.strip():
            raise ExtractionProviderError("ollama_empty_content", raw_output=raw)
        if not isinstance(model, str) or model != self._model:
            raise ExtractionProviderError("ollama_model_identity_mismatch", raw_output=raw)
        return StructuredExtractionResult(
            raw, model.rsplit(":", 1)[0], model, "atlas-ollama-chat", _ADAPTER_VERSION
        )
