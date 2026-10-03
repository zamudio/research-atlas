"""Small private HTTP boundary: one bounded POST, fixed errors, no retained envelopes."""

import asyncio
from collections.abc import Mapping
from typing import cast

import httpx
from pydantic import SecretStr

from research_atlas.providers import (
    ModelProviderError,
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
        raise ModelProviderError(f"{provider}_transport_failure") from None
    if not response.is_success:
        raise ModelProviderError(f"{provider}_http_failure")
    try:
        return object_fields(response.json())
    except ValueError, TypeError:
        raise ModelProviderError(f"{provider}_malformed_envelope") from None


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


def final_output(raw: bytes | None, provider: str) -> bytes:
    if raw is None or not raw.strip():
        raise ModelProviderError(f"{provider}_empty_output")
    return raw


def bearer_headers(key: SecretStr | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {key.get_secret_value()}"} if key is not None else {}
