"""Gemini v1 Interactions: one stateless request, final model-output text only."""

from collections.abc import Mapping
from copy import deepcopy

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


class GeminiInteractionsModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(settings.gemini_api_key, "Gemini")
        self._base_url = model_base_url(
            settings, "https://generativelanguage.googleapis.com/v1", api_key=self._key
        )
        self._timeout = settings.model_timeout_seconds
        self._client = client

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        assert self._key is not None
        fields = await post_json(
            self._client,
            self._base_url + "/interactions",
            {
                "model": self._model,
                "system_instruction": instructions,
                "input": [
                    {"type": "user_input", "content": [{"type": "text", "text": input_text}]}
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
            raise ModelProviderError("gemini_failed_response")
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
            raise ModelProviderError("gemini_malformed_envelope") from None
        if status != "completed":
            raise ModelProviderError("gemini_incomplete_response")
        return final_output(raw, "gemini")


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
