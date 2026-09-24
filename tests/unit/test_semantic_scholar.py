import asyncio
import json
from itertools import pairwise
from math import isclose

import httpx
import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.infrastructure.providers.semantic_scholar import (
    SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
    AsyncRequestRateLimiter,
    SemanticScholarLiteratureSource,
)


class FakeMonotonicClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.advance(delay)
        await asyncio.sleep(0)


def assert_floats_close(actual: list[float], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    assert all(isclose(left, right) for left, right in zip(actual, expected, strict=True))


def test_semantic_scholar_maps_mocked_paper() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/v1/paper/search"
        assert request.headers["x-api-key"] == "secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "abc123",
                        "externalIds": {
                            "DOI": "10.1000/EXAMPLE",
                            "ArXiv": "2401.01234v2",
                            "PubMed": "99",
                        },
                        "title": "A secondary result",
                        "authors": [{"name": "Casey Researcher"}],
                        "year": 2021,
                        "url": "https://www.semanticscholar.org/paper/abc123",
                        "publicationTypes": ["JournalArticle"],
                        "venue": "Example Journal",
                    }
                ]
            },
        )

    async def run_search():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SemanticScholarLiteratureSource("secret", client).search(
                LiteratureQuery("example topic", limit=5)
            )

    records = asyncio.run(run_search())

    record = records[0]
    assert record.title == "A secondary result"
    assert record.authors == ("Casey Researcher",)
    assert record.source_type == "journalarticle"
    assert {(item.namespace, item.value) for item in record.external_identifiers} >= {
        ("doi", "10.1000/example"),
        ("arxiv", "2401.01234"),
        ("pmid", "99"),
        ("semanticscholar", "abc123"),
    }


def test_back_to_back_requests_share_pacing_and_first_request_does_not_sleep() -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        return httpx.Response(200, json={"data": []})

    async def run_searches() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarLiteratureSource(
                client=client,
                clock=clock,
                sleep=clock.sleep,
            )
            await source.search(LiteratureQuery("first", limit=1))
            assert clock.delays == []
            await source.search(LiteratureQuery("second", limit=1))

    asyncio.run(run_searches())

    assert_floats_close(request_starts, [0.0, SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS])
    assert_floats_close(clock.delays, [SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS])


def test_concurrent_requests_are_serialized_and_paced() -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        return httpx.Response(200, json={"data": []})

    async def run_searches() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarLiteratureSource(
                client=client,
                clock=clock,
                sleep=clock.sleep,
            )
            await asyncio.gather(
                source.search(LiteratureQuery("first", limit=1)),
                source.search(LiteratureQuery("second", limit=1)),
                source.search(LiteratureQuery("third", limit=1)),
            )

    asyncio.run(run_searches())

    interval = SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS
    assert_floats_close(request_starts, [0.0, interval, interval * 2])
    assert_floats_close(
        [later - earlier for earlier, later in pairwise(request_starts)], [interval, interval]
    )


def test_rate_limiter_uses_injected_monotonic_elapsed_time() -> None:
    clock = FakeMonotonicClock(now=100.0)
    limiter = AsyncRequestRateLimiter(
        SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
        clock=clock,
        sleep=clock.sleep,
    )

    async def acquire_twice() -> None:
        await limiter.wait()
        clock.advance(0.4)
        await limiter.wait()

    asyncio.run(acquire_twice())

    assert_floats_close(clock.delays, [0.7])
    assert isclose(clock(), 101.1)


def test_retry_backoff_and_rate_limiter_compose() -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        if len(request_starts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarLiteratureSource(
                client=client,
                clock=clock,
                sleep=clock.sleep,
                retry_sleep=clock.sleep,
            )
            await source.search(LiteratureQuery("retry me", limit=1))

    asyncio.run(run_search())

    assert_floats_close(request_starts, [0.0, SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS])
    assert_floats_close(clock.delays, [0.5, 0.6])


def test_api_key_is_header_only_and_does_not_leak_into_provider_error() -> None:
    api_key = "sensitive-test-key"
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(401)

    async def run_discovery() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarLiteratureSource(api_key, client)
            with pytest.raises(DiscoveryFailedError) as caught:
                await DiscoverSources((source,)).execute(LiteratureQuery("safe query", limit=1))
            serialized = json.dumps(serialize_report(caught.value.report))
            assert api_key not in serialized
            assert caught.value.report.provider_outcomes[0].error_message == (
                "provider request failed with HTTP 401 Unauthorized"
            )

    asyncio.run(run_discovery())

    assert captured_request is not None
    assert captured_request.headers["x-api-key"] == api_key
    assert api_key not in str(captured_request.url)
    assert api_key not in captured_request.content.decode()
