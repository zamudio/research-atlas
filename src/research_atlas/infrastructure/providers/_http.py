"""Small shared retry policy for read-only provider HTTP calls."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx

from research_atlas.application.ports.literature_source import LiteratureSourceError

Sleep = Callable[[float], Awaitable[None]]
BeforeRequest = Callable[[], Awaitable[None]]
RetryDelayPolicy = Callable[[int, str | None, int], float]


@dataclass(frozen=True, slots=True)
class RequestAttemptEvent:
    """Secret-safe facts about one physical provider HTTP attempt."""

    provider: str
    operation_id: str
    endpoint_path: str
    attempt_number: int
    monotonic_start: float
    response_status: int | None
    retry_reason: str | None
    retry_delay: float | None


AttemptObserver = Callable[[RequestAttemptEvent], None]


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
        except (TypeError, ValueError, OverflowError):
            return None


def default_retry_delay(status_code: int, retry_after: str | None, attempt: int) -> float:
    """Use Retry-After when valid, otherwise the generic short backoff."""

    del status_code
    parsed_retry_after = parse_retry_after_delay(retry_after)
    if parsed_retry_after is not None:
        return parsed_retry_after
    return 0.5 * (2**attempt)


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str | int],
    headers: Mapping[str, str] | None = None,
    attempts: int = 3,
    sleep: Sleep = asyncio.sleep,
    before_request: BeforeRequest | None = None,
    retry_delay_policy: RetryDelayPolicy = default_retry_delay,
    attempt_observer: AttemptObserver | None = None,
    provider: str = "provider",
    operation_id: str = "provider.request",
    endpoint_path: str = "",
    clock: Callable[[], float] = monotonic,
) -> httpx.Response:
    """Retry rate limits, transient server responses, and transport failures."""

    last_error: httpx.TransportError | None = None
    for attempt in range(attempts):
        if before_request is not None:
            await before_request()
        start = clock()
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.TransportError as error:
            last_error = error
            exhausted = attempt + 1 == attempts
            delay = None if exhausted else default_retry_delay(0, None, attempt)
            if attempt_observer is not None:
                attempt_observer(
                    RequestAttemptEvent(
                        provider,
                        operation_id,
                        endpoint_path,
                        attempt + 1,
                        start,
                        None,
                        "transport_error_exhausted" if exhausted else "transport_error",
                        delay,
                    )
                )
            if exhausted:
                raise LiteratureSourceError(
                    "provider request failed due to a transport error",
                    error_type="transport_error",
                ) from error
            assert delay is not None
            await sleep(delay)
            continue
        if response.status_code != 429 and response.status_code < 500:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                if attempt_observer is not None:
                    attempt_observer(
                        RequestAttemptEvent(
                            provider,
                            operation_id,
                            endpoint_path,
                            attempt + 1,
                            start,
                            response.status_code,
                            "not_retryable",
                            None,
                        )
                    )
                raise LiteratureSourceError(
                    f"provider request failed with HTTP {response.status_code} "
                    f"{response.reason_phrase}",
                    error_type="http_status",
                    status_code=response.status_code,
                ) from error
            if attempt_observer is not None:
                attempt_observer(
                    RequestAttemptEvent(
                        provider,
                        operation_id,
                        endpoint_path,
                        attempt + 1,
                        start,
                        response.status_code,
                        None,
                        None,
                    )
                )
            return response
        exhausted = attempt + 1 == attempts
        retry_reason = "rate_limit" if response.status_code == 429 else "server_error"
        delay = (
            None
            if exhausted
            else retry_delay_policy(
                response.status_code,
                response.headers.get("Retry-After"),
                attempt,
            )
        )
        if attempt_observer is not None:
            attempt_observer(
                RequestAttemptEvent(
                    provider,
                    operation_id,
                    endpoint_path,
                    attempt + 1,
                    start,
                    response.status_code,
                    f"{retry_reason}_exhausted" if exhausted else retry_reason,
                    delay,
                )
            )
        if exhausted:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                raise LiteratureSourceError(
                    f"provider request failed with HTTP {response.status_code} "
                    f"{response.reason_phrase}",
                    error_type="http_status",
                    status_code=response.status_code,
                ) from error
        assert delay is not None
        await sleep(delay)
    if last_error is not None:
        raise LiteratureSourceError(
            "provider request failed due to a transport error",
            error_type="transport_error",
        ) from last_error
    raise RuntimeError("provider request retry loop ended unexpectedly")
