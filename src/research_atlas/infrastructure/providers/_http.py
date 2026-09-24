"""Small shared retry policy for read-only provider HTTP calls."""

import asyncio
from collections.abc import Mapping

import httpx


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int],
    headers: Mapping[str, str] | None = None,
    attempts: int = 3,
) -> httpx.Response:
    """Retry rate limits, transient server responses, and transport failures."""

    last_error: httpx.TransportError | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError as error:
            last_error = error
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(0.2 * (attempt + 1))
            continue
        if response.status_code != 429 and response.status_code < 500:
            response.raise_for_status()
            return response
        if attempt + 1 == attempts:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After", "")
        try:
            delay = min(float(retry_after), 2.0)
        except ValueError:
            delay = 0.2 * (attempt + 1)
        await asyncio.sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("provider request retry loop ended unexpectedly")
