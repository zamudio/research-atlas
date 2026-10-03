"""Native Anthropic Messages JSON output; no tools or retained thinking blocks."""

from collections.abc import Mapping
from typing import cast

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
    array_items,
    final_output,
    object_fields,
    post_json,
    text_bytes,
)

_API_VERSION = "2023-06-01"


class AnthropicModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(settings.anthropic_api_key, "Anthropic")
        self._base_url = model_base_url(settings, "https://api.anthropic.com/v1", api_key=self._key)
        self._timeout = settings.model_timeout_seconds
        self._max_tokens = settings.model_max_output_tokens
        self._client = client

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        assert self._key is not None
        fields = await post_json(
            self._client,
            self._base_url + "/messages",
            {
                "model": self._model,
                "system": instructions,
                "messages": [{"role": "user", "content": input_text}],
                "stream": False,
                "max_tokens": self._max_tokens,
                "output_config": {
                    "format": {"type": "json_schema", "schema": anthropic_schema(schema)}
                },
            },
            {"x-api-key": self._key.get_secret_value(), "anthropic-version": _API_VERSION},
            self._timeout,
            "anthropic",
        )
        try:
            if fields.get("type") != "message" or fields.get("role") != "assistant":
                raise ValueError
            texts: list[str] = []
            for value in array_items(fields.get("content")):
                block = object_fields(value)
                if block.get("type") in ("thinking", "redacted_thinking"):
                    continue
                if block.get("type") != "text" or not isinstance(block.get("text"), str):
                    raise ValueError
                texts.append(str(block["text"]))
            raw = text_bytes(texts)
        except ValueError, TypeError, UnicodeError:
            raise ModelProviderError("anthropic_malformed_envelope") from None
        if fields.get("stop_reason") == "refusal":
            raise ModelProviderError("anthropic_refusal")
        if fields.get("stop_reason") != "end_turn" or fields.get("stop_sequence") is not None:
            raise ModelProviderError("anthropic_incomplete_response")
        return final_output(raw, "anthropic")


def anthropic_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """Translate unsupported bounds into descriptions without mutating the canonical schema.

    The application always validates exact returned bytes with the original Atlas schema.
    Property/definition maps are visited as maps, so field names resembling keywords survive.
    """
    result: dict[str, object] = {}
    constraints: list[str] = []
    for name, value in schema.items():
        if name in {"minLength", "maxLength", "maxItems"} or (
            name == "minItems" and value not in (0, 1)
        ):
            constraints.append(f"{name}={value}")
        elif name in {"properties", "$defs", "definitions"}:
            result[name] = {
                key: anthropic_schema(object_fields(item))
                for key, item in object_fields(value).items()
            }
        elif isinstance(value, dict):
            result[name] = anthropic_schema(cast(dict[str, object], value))
        elif isinstance(value, list):
            result[name] = [
                anthropic_schema(cast(dict[str, object], item)) if isinstance(item, dict) else item
                for item in cast(list[object], value)
            ]
        else:
            result[name] = value
    if constraints:
        description = str(result.get("description", ""))
        result["description"] = (
            description + " Atlas constraints: " + ", ".join(constraints)
        ).strip()
    return result
