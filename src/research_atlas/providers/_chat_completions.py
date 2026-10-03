"""Shared wire shape only; native routing and endpoint policy stay in public adapters."""

import json
from collections.abc import Mapping

from research_atlas.providers import ModelProviderError
from research_atlas.providers._http import array_items, object_fields


def chat_payload(
    model: str, instructions: str, input_text: str, schema: Mapping[str, object]
) -> dict[str, object]:
    return {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "atlas_output", "strict": True, "schema": dict(schema)},
        },
    }


def chat_text(fields: dict[str, object], provider: str) -> bytes:
    if fields.get("error") is not None:
        raise ModelProviderError(f"{provider}_failed_response")
    try:
        choices = array_items(fields.get("choices"))
        if len(choices) != 1:
            raise ValueError
        choice = object_fields(choices[0])
        message = object_fields(choice.get("message"))
        if message.get("role") != "assistant":
            raise ValueError
        if message.get("refusal") is not None or choice.get("finish_reason") == "content_filter":
            raise ModelProviderError(f"{provider}_refusal")
        if message.get("tool_calls") or message.get("function_call"):
            raise ValueError
        text = message.get("content")
        if not isinstance(text, str):
            raise ValueError
        raw = text.encode("utf-8")
    except ValueError, TypeError, UnicodeError:
        raise ModelProviderError(f"{provider}_malformed_envelope") from None
    if choice.get("finish_reason") != "stop":
        raise ModelProviderError(f"{provider}_incomplete_response")
    if not raw.strip():
        raise ModelProviderError(f"{provider}_empty_output")
    # An endpoint that ignores response_format must fail explicitly, never heal or downgrade.
    try:
        if not isinstance(json.loads(raw), dict):
            raise ValueError
    except ValueError, UnicodeError:
        raise ModelProviderError(f"{provider}_invalid_structured_output") from None
    return raw
