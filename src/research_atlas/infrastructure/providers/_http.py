"""Small shared retry policy for read-only provider HTTP calls."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from research_atlas.application.ports.literature_source import LiteratureSourceError

Sleep = Callable[[float], Awaitable[None]]
BeforeRequest = Callable[[], Awaitable[None]]


def parse_retry_after_delay(retry_after: str | None) -> float | None:
    """Parse Retry-After without treating invalid values as zero."""

    if retry_after is None:
        return None
    try:
        return max(0.0, float(retry_after))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        except TypeError, ValueError, OverflowError:
            return None


def default_retry_delay(retry_after: str | None, attempt: int) -> float:
    """Use Retry-After when valid, otherwise the generic short backoff."""

    parsed_retry_after = parse_retry_after_delay(retry_after)
    if parsed_retry_after is not None:
        return parsed_retry_after
    return 0.5 * (2**attempt)


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise LiteratureSourceError(
            f"provider request failed with HTTP {response.status_code} {response.reason_phrase}",
            error_type="http_status",
            status_code=response.status_code,
        ) from error


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int],
    headers: Mapping[str, str] | None = None,
    attempts: int = 3,
    sleep: Sleep = asyncio.sleep,
    before_request: BeforeRequest | None = None,
) -> httpx.Response:
    """Retry transient failures with safe errors and optional provider pacing."""

    for attempt in range(attempts):
        if before_request is not None:
            await before_request()
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError as error:
            if attempt + 1 == attempts:
                raise LiteratureSourceError(
                    "provider request failed due to a transport error",
                    error_type="transport_error",
                ) from error
            await sleep(default_retry_delay(None, attempt))
            continue
        if response.status_code != 429 and response.status_code < 500:
            _raise_for_status(response)
            return response
        if attempt + 1 == attempts:
            _raise_for_status(response)
        await sleep(default_retry_delay(response.headers.get("Retry-After"), attempt))
    raise RuntimeError("provider request retry loop ended unexpectedly")
