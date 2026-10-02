"""Gemini v1 Interactions: one stateless request, final model-output text only."""

from collections.abc import Mapping
from copy import deepcopy

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
    array_items,
    extraction_result,
    object_fields,
    post_json,
    text_bytes,
)

_VERSION = "atlas.gemini-interactions.v1"
_SCHEMA_VERSION = "atlas.gemini-schema.v1"


class GeminiInteractionsExtractor:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = extraction_model(settings)
        self._key = extraction_credential(settings.gemini_api_key, "Gemini")
        self._base_url = extraction_base_url(
            settings, "https://generativelanguage.googleapis.com/v1", api_key=self._key
        )
        self._timeout = settings.extraction_timeout_seconds
        self._client = client

    @property
    def configuration(self) -> Mapping[str, object]:
        return {
            "adapter": _VERSION,
            "provider": "gemini",
            "base_url": self._base_url,
            "model": self._model,
            "timeout_seconds": self._timeout,
            "structured_output": "json_schema",
            "schema_transform": _SCHEMA_VERSION,
            "mime_type": "application/json",
            "stream": False,
            "store": False,
            "background": False,
        }

    async def extract(
        self, instructions: str, document_text: str, schema: Mapping[str, object]
    ) -> StructuredExtractionResult:
        assert self._key is not None
        fields = await post_json(
            self._client,
            self._base_url + "/interactions",
            {
                "model": self._model,
                "system_instruction": instructions,
                "input": [
                    {"type": "user_input", "content": [{"type": "text", "text": document_text}]}
                ],
                "stream": False,
                "store": False,
                "background": False,
                "response_format": {
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": gemini_schema(schema),
                },
            },
            {"x-goog-api-key": self._key.get_secret_value()},
            self._timeout,
            "gemini",
        )
        status = fields.get("status")
        if status in ("failed", "cancelled"):
            # A failed interaction can include safety/refusal explanations, never retain them.
            raise ExtractionProviderError("gemini_failed_response")
        try:
            if status not in ("completed", "incomplete", "in_progress", "requires_action"):
                raise ValueError
            final: dict[str, object] | None = None
            for value in array_items(fields.get("steps")):
                step = object_fields(value)
                if step.get("type") == "model_output":
                    final = step
                # Thought summaries, input echoes and execution steps are discarded.
            texts: list[str] = []
            if final is not None:
                for value in array_items(final.get("content")):
                    content = object_fields(value)
                    if content.get("type") != "text":
                        continue
                    text = content.get("text")
                    if not isinstance(text, str):
                        raise ValueError
                    texts.append(text)
            raw = text_bytes(texts)
        except ValueError, TypeError, UnicodeError:
            raise ExtractionProviderError("gemini_malformed_envelope") from None
        if status != "completed":
            raise ExtractionProviderError("gemini_incomplete_response", raw_output=raw)
        # model is optional in the Interactions response; retain requested identity if absent.
        return extraction_result(
            raw,
            fields.get("model", self._model),
            "gemini",
            "atlas-gemini-interactions",
            _VERSION,
            self._key,
        )


def gemini_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Project Atlas's string constraints into Gemini descriptions, without mutation.

    Only schema nodes used by canonical Atlas are traversed. Property/definition names
    are map keys, never schema keywords. All other fields, including array bounds,
    remain intact; the application validates returned bytes against the original schema.
    """
    result = deepcopy(dict(schema))
    constraints = [
        f"{name}={result.pop(name)}"
        for name in ("minLength", "maxLength", "pattern")
        if name in result
    ]
    if constraints:
        description = result.get("description", "")
        prefix = f"{description} " if description else ""
        result["description"] = prefix + "Atlas constraints: " + ", ".join(constraints)
    for name in ("properties", "$defs"):
        if name in result:
            result[name] = {
                key: gemini_schema(object_fields(value))
                for key, value in object_fields(result[name]).items()
            }
    if "items" in result:
        result["items"] = gemini_schema(object_fields(result["items"]))
    if "anyOf" in result:
        result["anyOf"] = [
            gemini_schema(object_fields(value)) for value in array_items(result["anyOf"])
        ]
    return result
