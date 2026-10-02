"""Small private HTTP boundary: one bounded POST, fixed errors, no retained envelopes."""

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx
from pydantic import SecretStr

from research_atlas.application.ports.extraction import (
    ExtractionProviderError,
    StructuredExtractionResult,
)


async def post_json(
    client: httpx.AsyncClient | None,
    url: str,
    payload: Mapping[str, object],
    headers: Mapping[str, str],
    timeout: float,
    provider: str,
) -> dict[str, object]:
    if client is None:
        async with httpx.AsyncClient(timeout=timeout) as owned_client:
            return await post_json(owned_client, url, payload, headers, timeout, provider)
    try:
        async with asyncio.timeout(timeout):
            response = await client.post(
                url, json=dict(payload), headers=headers, timeout=timeout, follow_redirects=False
            )
    except httpx.HTTPError, TimeoutError:
        raise ExtractionProviderError(f"{provider}_transport_failure") from None
    if not response.is_success:
        raise ExtractionProviderError(f"{provider}_http_failure")
    try:
        return object_fields(response.json())
    except ValueError, TypeError:
        raise ExtractionProviderError(f"{provider}_malformed_envelope") from None


def object_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError
    return cast(dict[str, object], value)


def array_items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError
    return cast(list[object], value)


def text_bytes(texts: list[str]) -> bytes | None:
    return "".join(texts).encode("utf-8") if texts else None


def extraction_result(
    raw: bytes | None,
    model: object,
    provider: str,
    tool: str,
    version: str,
    key: SecretStr | None,
) -> StructuredExtractionResult:
    if raw is None or not raw.strip():
        raise ExtractionProviderError(f"{provider}_empty_output", raw_output=raw)
    if (
        not isinstance(model, str)
        or not model.strip()
        or len(model) > 200
        or any(ord(char) < 32 or ord(char) == 127 for char in model)
        or (key is not None and key.get_secret_value() in model)
    ):
        raise ExtractionProviderError(f"{provider}_model_identity_missing", raw_output=raw)
    return StructuredExtractionResult(raw, model, model, tool, version)


def bearer_headers(key: SecretStr | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key.get_secret_value()}"} if key is not None else {}
