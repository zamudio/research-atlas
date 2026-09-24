"""Small shared retry policy for read-only provider HTTP calls."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from research_atlas.application.ports.literature_source import LiteratureSourceError

Sleep = Callable[[float], Awaitable[None]]


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return 0.5 * (2**attempt)


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int],
    headers: Mapping[str, str] | None = None,
    attempts: int = 3,
    sleep: Sleep = asyncio.sleep,
) -> httpx.Response:
    """Retry rate limits, transient server responses, and transport failures."""

    last_error: httpx.TransportError | None = None
    for attempt in range(attempts):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError as error:
            last_error = error
            if attempt + 1 == attempts:
                raise LiteratureSourceError(str(error), error_type="transport_error") from error
            await sleep(_retry_delay(None, attempt))
            continue
        if response.status_code != 429 and response.status_code < 500:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise LiteratureSourceError(
                    f"provider request failed with HTTP {response.status_code} "
                    f"{response.reason_phrase}",
                    error_type="http_status",
                    status_code=response.status_code,
                ) from error
            return response
        if attempt + 1 == attempts:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise LiteratureSourceError(
                    f"provider request failed with HTTP {response.status_code} "
                    f"{response.reason_phrase}",
                    error_type="http_status",
                    status_code=response.status_code,
                ) from error
        await sleep(_retry_delay(response.headers.get("Retry-After"), attempt))
    if last_error is not None:
        raise LiteratureSourceError(str(last_error), error_type="transport_error") from last_error
    raise RuntimeError("provider request retry loop ended unexpectedly")
