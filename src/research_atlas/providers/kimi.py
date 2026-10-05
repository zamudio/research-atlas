"""Native Kimi strict Chat Completions; final assistant content only."""

from collections.abc import Mapping
from copy import deepcopy

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers._chat_completions import chat_payload, chat_text
from research_atlas.providers._config import (
    model_base_url,
    model_context_capacity,
    model_credential,
    model_name,
    request_fits_context,
)
from research_atlas.providers._http import (
    array_items,
    bearer_headers,
    final_output,
    object_fields,
    post_json,
)


class KimiModel:
    def __init__(
        self, settings: ProviderSettings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        self._key = model_credential(settings.kimi_api_key, "Kimi")
        self._base_url = model_base_url(settings, "https://api.moonshot.ai/v1", api_key=self._key)
        self._timeout = settings.model_timeout_seconds
        self._client = client
        self._context_tokens = model_context_capacity(settings, "kimi")
        self._output_tokens = settings.model_max_output_tokens

    async def fits_context(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bool:
        return request_fits_context(
            chat_payload(self._model, instructions, input_text, kimi_schema(schema)),
            self._context_tokens,
            self._output_tokens,
            "kimi",
        )

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        fields = await post_json(
            self._client,
            self._base_url + "/chat/completions",
            chat_payload(self._model, instructions, input_text, kimi_schema(schema)),
            bearer_headers(self._key),
            self._timeout,
            "kimi",
        )
        return final_output(chat_text(fields, "kimi"), "kimi")


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
