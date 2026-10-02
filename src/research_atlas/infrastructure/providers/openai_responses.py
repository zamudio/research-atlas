"""OpenAI Responses reference adapter using httpx and stateless strict output."""

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx

from research_atlas.application.ports.extraction import (
    ExtractionProviderError,
    StructuredExtractionResult,
)
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers._extraction_config import (
    extraction_base_url,
    extraction_model,
)

_ADAPTER_VERSION = "atlas.openai-responses.v1"
_SCHEMA_NAME = "atlas_extraction"


class OpenAIResponsesExtractor:
    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._base_url = extraction_base_url(settings, "https://api.openai.com/v1")
        key = settings.extraction_api_key
        if key is None or not key.get_secret_value().strip():
            raise ValueError("OpenAI extraction API key must be configured")
        self._api_key = key
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _ADAPTER_VERSION,
            "provider": "openai",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_name": _SCHEMA_NAME,
            "strict": True,
            "store": False,
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
            "instructions": instructions,
            "input": document_text,
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
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.post(
                    self._base_url + "/responses",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    timeout=self._timeout,
                    follow_redirects=False,
                )
        except httpx.HTTPError, TimeoutError:
            raise ExtractionProviderError("openai_transport_failure") from None
        if not response.is_success:
            raise ExtractionProviderError("openai_http_failure")
        try:
            envelope: object = response.json()
            fields = _object(envelope)
            status = fields.get("status")
            if status not in {
                "completed",
                "incomplete",
                "failed",
                "cancelled",
                "queued",
                "in_progress",
            }:
                raise ValueError
            output = fields.get("output")
            if not isinstance(output, list):
                raise ValueError
            texts: list[str] = []
            refused = False
            message_incomplete = False
            final_messages = 0
            for value in cast(list[object], output):
                item = _object(value)
                if item.get("type") == "reasoning":
                    continue  # Never copy reasoning, summaries or encrypted content.
                if item.get("type") != "message" or item.get("role") != "assistant":
                    raise ValueError
                phase = item.get("phase")
                if phase == "commentary":
                    continue
                if phase not in {None, "final_answer"}:
                    raise ValueError
                final_messages += 1
                if final_messages > 1:
                    raise ValueError
                message_status = item.get("status")
                if message_status not in {"completed", "incomplete", "in_progress"}:
                    raise ValueError
                message_incomplete = message_status != "completed"
                content = item.get("content")
                if not isinstance(content, list):
                    raise ValueError
                for part in cast(list[object], content):
                    segment = _object(part)
                    if segment.get("type") == "refusal":
                        refused = True  # Refusal explanation is not structured model output.
                    elif segment.get("type") == "output_text":
                        text = segment.get("text")
                        if not isinstance(text, str):
                            raise ValueError
                        texts.append(text)
                    else:
                        raise ValueError
            raw = "".join(texts).encode("utf-8") if texts else None
        except ValueError, TypeError, UnicodeError:
            raise ExtractionProviderError("openai_malformed_envelope") from None
        if refused:
            raise ExtractionProviderError("openai_refusal")
        if status in {"failed", "cancelled"} or fields.get("error") is not None:
            raise ExtractionProviderError("openai_failed_response", raw_output=raw)
        if (
            status != "completed"
            or message_incomplete
            or fields.get("incomplete_details") is not None
        ):
            raise ExtractionProviderError("openai_incomplete_response", raw_output=raw)
        if raw is None or not raw.strip():
            raise ExtractionProviderError("openai_empty_output", raw_output=raw)
        model = fields.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ExtractionProviderError("openai_model_identity_missing", raw_output=raw)
        # The provider may resolve a requested alias to a concrete snapshot.
        return StructuredExtractionResult(
            raw, model, model, "atlas-openai-responses", _ADAPTER_VERSION
        )


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError
    return cast(dict[str, object], value)
