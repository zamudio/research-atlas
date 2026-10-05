"""Ollama reference adapter; one generation, no reasoning retention."""

import asyncio
import json
from collections.abc import Mapping
from typing import cast

import httpx

from research_atlas.config import ProviderSettings
from research_atlas.providers import (
    ModelProviderError,
)
from research_atlas.providers._config import (
    model_base_url,
    model_name,
)
from research_atlas.providers._http import array_items, bearer_headers, object_fields, post_json


def _request_context_tokens(
    messages: list[dict[str, str]],
    schema: Mapping[str, object],
    template_bytes: int,
    model_message_overhead: int,
    output_tokens: int,
) -> int:
    """Reserve one token per UTF-8 byte, including framing, plus output headroom.

    Template source bytes are reserved per message and for the assistant prefix,
    conservatively covering repeated turn wrappers without rendering the template.
    """
    try:
        material = json.dumps({"messages": messages, "format": dict(schema)}, ensure_ascii=False)
        return (
            len(material.encode("utf-8"))
            + template_bytes * (len(messages) + 1)
            + model_message_overhead
            + output_tokens
        )
    except TypeError, ValueError, UnicodeError:
        raise ModelProviderError("ollama_invalid_request_material") from None


class OllamaModel:
    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = settings or ProviderSettings()
        self._model = model_name(settings)
        key = settings.ollama_api_key
        self._api_key = key if key is not None and key.get_secret_value().strip() else None
        self._base_url = model_base_url(settings, "http://localhost:11434", api_key=self._api_key)
        self._timeout = settings.model_timeout_seconds
        self._client = client
        self._context_override = settings.model_context_tokens
        self._max_output_tokens = settings.model_max_output_tokens
        self._advertised_context: int | None = None
        self._template_bytes = 0
        self._model_message_overhead = 0

    async def _context_ceiling(self, client: httpx.AsyncClient | None) -> int:
        if self._advertised_context is None:
            fields = await post_json(
                client,
                self._base_url + "/api/show",
                {"model": self._model},
                bearer_headers(self._api_key),
                self._timeout,
                "ollama",
            )
            try:
                info = object_fields(fields.get("model_info"))
                # Ollama uses architecture-specific keys such as llama.context_length.
                contexts = [
                    (key, value) for key, value in info.items() if key.endswith(".context_length")
                ]
                if len(contexts) != 1:
                    raise ValueError
                key, context = contexts[0]
                if key == ".context_length" or type(context) is not int or context <= 0:
                    raise ValueError
            except ValueError:
                raise ModelProviderError("ollama_invalid_context_metadata") from None
            try:
                template = fields.get("template", "")
                if not isinstance(template, str):
                    raise ValueError
                template_bytes = len(template.encode("utf-8"))
                # Ollama prepends any messages embedded in the selected model.
                model_messages = array_items(fields.get("messages", []))
                model_message_overhead = (
                    len(json.dumps(model_messages, ensure_ascii=False).encode("utf-8"))
                    + template_bytes * len(model_messages)
                    if model_messages
                    else 0
                )
            except ValueError, TypeError, UnicodeError:
                raise ModelProviderError("ollama_invalid_template_metadata") from None
            self._template_bytes = template_bytes
            self._model_message_overhead = model_message_overhead
            self._advertised_context = context
        if self._context_override is not None:
            if self._context_override > self._advertised_context:
                raise ModelProviderError("ollama_context_override_exceeds_maximum")
            return self._context_override
        return self._advertised_context

    def _context_requirement(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> int:
        return _request_context_tokens(
            [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            schema,
            self._template_bytes,
            self._model_message_overhead,
            self._max_output_tokens,
        )

    async def fits_context(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bool:
        ceiling = await self._context_ceiling(self._client)
        return self._context_requirement(instructions, input_text, schema) <= ceiling

    async def generate(
        self, instructions: str, input_text: str, schema: Mapping[str, object]
    ) -> bytes:
        if self._client is not None:
            return await self._generate(self._client, instructions, input_text, schema)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await self._generate(client, instructions, input_text, schema)

    async def _generate(
        self,
        client: httpx.AsyncClient,
        instructions: str,
        input_text: str,
        schema: Mapping[str, object],
    ) -> bytes:
        ceiling = await self._context_ceiling(client)
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": input_text},
        ]
        output_schema = dict(schema)
        context_tokens = self._context_requirement(instructions, input_text, output_schema)
        if context_tokens > ceiling:
            raise ModelProviderError("ollama_context_requirement_exceeds_limit")
        payload = {
            "model": self._model,
            "stream": False,
            "think": False,
            "format": output_schema,
            "messages": messages,
            "options": {
                "temperature": 0,
                "num_ctx": context_tokens,
                "num_predict": self._max_output_tokens,
            },
        }
        try:
            async with asyncio.timeout(self._timeout):
                response = await client.post(
                    self._base_url + "/api/chat",
                    json=payload,
                    headers=(
                        {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
                        if self._api_key is not None
                        else {}
                    ),
                    timeout=self._timeout,
                    follow_redirects=False,
                )
        except httpx.HTTPError, TimeoutError:
            raise ModelProviderError("ollama_transport_failure") from None
        if not response.is_success:
            raise ModelProviderError("ollama_http_failure")
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
            raise ModelProviderError("ollama_malformed_envelope") from None
        if fields.get("done") is not True or (
            "done_reason" in fields and fields["done_reason"] != "stop"
        ):
            raise ModelProviderError("ollama_incomplete_completion")
        if not content.strip():
            raise ModelProviderError("ollama_empty_content")
        if not isinstance(model, str) or model != self._model:
            raise ModelProviderError("ollama_model_identity_mismatch")
        return raw
