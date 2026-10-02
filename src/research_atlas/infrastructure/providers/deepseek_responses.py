"""Native stateless DeepSeek Responses; no JSON-mode downgrade or provider fallback."""

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
    extraction_credential,
    extraction_model,
)
from research_atlas.infrastructure.providers._extraction_http import (
    bearer_headers,
    extraction_result,
    post_json,
)
from research_atlas.infrastructure.providers._responses import response_text

_VERSION = "atlas.deepseek-responses.v1"


class DeepSeekResponsesExtractor:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._key = extraction_credential(settings.deepseek_api_key, "DeepSeek")
        self._base_url = extraction_base_url(
            settings, "https://api.deepseek.com", api_key=self._key
        )
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _VERSION,
            "provider": "deepseek",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_name": "atlas_extraction",
            "stream": False,
            "store": False,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        # DeepSeek is stateless by contract. store is unsupported; do not depend on it.
        # Its documented text.format has no strict switch: json_schema enforces the schema.
        fields = await post_json(
            self._client,
            self._base_url + "/responses",
            {
                "model": self._model,
                "instructions": instructions,
                "input": document_text,
                "stream": False,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "atlas_extraction",
                        "schema": dict(schema),
                    }
                },
            },
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
            raise ExtractionProviderError("deepseek_malformed_envelope") from None
        if refused:
            raise ExtractionProviderError("deepseek_refusal")
        details = fields.get("incomplete_details")
        if (
            isinstance(details, dict)
            and cast(dict[str, object], details).get("reason") == "content_filter"
        ):
            raise ExtractionProviderError("deepseek_refusal")
        if status == "failed" or fields.get("error") is not None:
            raise ExtractionProviderError("deepseek_failed_response", raw_output=raw)
        if status != "completed" or message_incomplete or details is not None:
            raise ExtractionProviderError("deepseek_incomplete_response", raw_output=raw)
        return extraction_result(
            raw, fields.get("model"), "deepseek", "atlas-deepseek-responses", _VERSION, self._key
        )
