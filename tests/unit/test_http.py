import asyncio

import httpx

from research_atlas.application.ports.literature_source import LiteratureSourceError
from research_atlas.infrastructure.providers._http import get_with_retries


def test_retry_after_delay_is_respected_without_old_cap() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def run_request() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await get_with_retries(client, "https://example.test", params={}, sleep=sleep)

    asyncio.run(run_request())

    assert calls == 2
    assert delays == [7.0]


def test_retryable_responses_use_deterministic_exponential_backoff() -> None:
    calls = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(200)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def run_request() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await get_with_retries(client, "https://example.test", params={}, sleep=sleep)

    asyncio.run(run_request())

    assert calls == 3
    assert delays == [0.5, 1.0]


def test_exhausted_retries_surface_http_error() -> None:
    async def sleep(_delay: float) -> None:
        pass

    async def run_request() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503))
        ) as client:
            await get_with_retries(client, "https://example.test", params={}, sleep=sleep)

    try:
        asyncio.run(run_request())
    except LiteratureSourceError as error:
        assert error.error_type == "http_status"
        assert error.status_code == 503
        assert str(error) == "provider request failed with HTTP 503 Service Unavailable"
        assert "example.test" not in str(error)
    else:
        raise AssertionError("exhausted retries did not surface a provider-neutral error")


def test_transport_error_details_are_not_surfaced() -> None:
    sensitive_detail = "request headers contained a sensitive value"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(sensitive_detail, request=request)

    async def sleep(_delay: float) -> None:
        pass

    async def run_request() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await get_with_retries(client, "https://example.test", params={}, sleep=sleep)

    try:
        asyncio.run(run_request())
    except LiteratureSourceError as error:
        assert error.error_type == "transport_error"
        assert str(error) == "provider request failed due to a transport error"
        assert sensitive_detail not in str(error)
    else:
        raise AssertionError("exhausted retries did not surface a provider-neutral error")
