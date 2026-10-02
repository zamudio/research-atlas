"""Native Kimi strict Chat Completions; final assistant content only."""

from collections.abc import Mapping
from copy import deepcopy

import httpx

from research_atlas.application.ports.extraction import StructuredExtractionResult
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers._chat_completions import chat_payload, chat_text
from research_atlas.infrastructure.providers._extraction_config import (
    extraction_base_url,
    extraction_credential,
    extraction_model,
)
from research_atlas.infrastructure.providers._extraction_http import (
    array_items,
    bearer_headers,
    extraction_result,
    object_fields,
    post_json,
)

_VERSION = "atlas.kimi-chat.v1"
_SCHEMA_VERSION = "atlas.kimi-schema.v1"


class KimiExtractor:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._key = extraction_credential(settings.kimi_api_key, "Kimi")
        self._base_url = extraction_base_url(
            settings, "https://api.moonshot.ai/v1", api_key=self._key
        )
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _VERSION,
            "provider": "kimi",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_name": "atlas_extraction",
            "schema_transform": _SCHEMA_VERSION,
            "strict": True,
            "stream": False,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            chat_payload(self._model, instructions, document_text, kimi_schema(schema)),
            bearer_headers(self._key),
            self._timeout,
            "kimi",
        )
        return extraction_result(
            chat_text(fields, "kimi"),
            fields.get("model", self._model),
            "kimi",
            "atlas-kimi-chat",
            _VERSION,
            self._key,
        )


def kimi_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Move only patterns into descriptions; MFJS marks pattern as future support.

    Moonshot's walle model/validators support Atlas's titles, string/array bounds,
    closed objects, nullable anyOf and internal references. Preserve those verbatim.
    Traverse schema nodes, never property/definition names, without mutating Atlas's
    authoritative schema. The application still validates every canonical constraint.
    """
    result = deepcopy(dict(schema))
    if "pattern" in result:
        constraint = f"Atlas constraints: pattern={result.pop('pattern')}"
        description = result.get("description", "")
        result["description"] = f"{description} {constraint}" if description else constraint
    for name in ("properties", "$defs"):
        if name in result:
            result[name] = {
                key: kimi_schema(object_fields(value))
                for key, value in object_fields(result[name]).items()
            }
    if "items" in result:
        result["items"] = kimi_schema(object_fields(result["items"]))
    if "anyOf" in result:
        result["anyOf"] = [
            kimi_schema(object_fields(value)) for value in array_items(result["anyOf"])
        ]
    return result
