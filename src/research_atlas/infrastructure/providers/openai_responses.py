"""OpenAI Responses reference adapter using httpx and stateless strict output."""

from collections.abc import Mapping

import httpx

from research_atlas.application.ports.extraction import (
    ExtractionProviderError,
    StructuredExtractionResult,
)
from research_atlas.infrastructure.config import ProviderSettings
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
from research_atlas.infrastructure.providers._responses import response_text

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
        self._api_key = extraction_credential(
            preferred_credential(settings.openai_api_key, settings.extraction_api_key), "OpenAI"
        )
        self._base_url = extraction_base_url(
            settings, "https://api.openai.com/v1", api_key=self._api_key
        )
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
        # The provider may resolve a requested alias to a concrete snapshot.
        return extraction_result(
            raw,
            fields.get("model"),
            "openai",
            "atlas-openai-responses",
            _ADAPTER_VERSION,
            self._api_key,
        )
