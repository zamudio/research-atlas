import asyncio
import json
from math import isclose

import httpx
import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSearchRequest,
)
from research_atlas.domain.studies import SourceRecord
from research_atlas.infrastructure.providers import semantic_scholar
from research_atlas.infrastructure.providers.semantic_scholar import (
    SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
    AsyncRequestCoordinator,
    SemanticScholarBulkSearch,
    SemanticScholarRelevanceSearch,
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


def isolated_coordinator(clock: FakeMonotonicClock) -> AsyncRequestCoordinator:
    return AsyncRequestCoordinator(
        SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
        clock=clock,
        sleep=clock.sleep,
    )


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
        clock = FakeMonotonicClock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SemanticScholarRelevanceSearch(
                "secret", client, request_coordinator=isolated_coordinator(clock)
            ).search(LiteratureQuery("example topic", limit=5))

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


def test_bulk_search_uses_boolean_endpoint_and_stops_at_limit_across_pages() -> None:
    requests: list[httpx.Request] = []

    def paper(index: int) -> dict[str, object]:
        return {
            "paperId": f"s2-{index}",
            "externalIds": {"DOI": f"10.1000/{index}"},
            "title": f"Bulk result {index}",
            "authors": [{"name": "A. Researcher"}],
            "year": 2020 + index,
            "url": f"https://www.semanticscholar.org/paper/s2-{index}",
            "publicationTypes": ["JournalArticle"],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/graph/v1/paper/search/bulk"
        assert request.url.params["query"] == '"intelligent tutoring systems" AND review'
        if len(requests) == 1:
            assert "token" not in request.url.params
            return httpx.Response(200, json={"data": [paper(1), paper(2)], "token": "next"})
        assert request.url.params["token"] == "next"
        return httpx.Response(200, json={"data": [paper(3), paper(4)]})

    async def run_search() -> tuple[SourceRecord, ...]:
        clock = FakeMonotonicClock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SemanticScholarBulkSearch(
                client=client,
                request_coordinator=isolated_coordinator(clock),
            ).search(LiteratureQuery('"intelligent tutoring systems" AND review', limit=3))

    records = asyncio.run(run_search())

    assert len(requests) == 2
    assert [record.title for record in records] == [
        "Bulk result 1",
        "Bulk result 2",
        "Bulk result 3",
    ]
    assert all(
        {item.provider for item in record.provider_provenance} == {"semantic_scholar"}
        for record in records
    )


def test_two_default_instances_share_pacing_and_first_request_does_not_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []
    monkeypatch.setattr(
        semantic_scholar,
        "_DEFAULT_REQUEST_COORDINATOR",
        isolated_coordinator(clock),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        return httpx.Response(200, json={"data": []})

    async def run_searches() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first_source = SemanticScholarRelevanceSearch(client=client)
            second_source = SemanticScholarBulkSearch(client=client)
            await first_source.search(LiteratureQuery("first", limit=1))
            assert clock.delays == []
            await second_source.search(LiteratureQuery("second", limit=1))

    asyncio.run(run_searches())

    assert_floats_close(request_starts, [0.0, SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS])
    assert_floats_close(clock.delays, [SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS])


def test_concurrent_requests_across_instances_reserve_separate_slots() -> None:
    request_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"data": []})

    async def run_searches() -> None:
        delays: list[float] = []
        reservations_ready = asyncio.Event()
        release_sleepers = asyncio.Event()

        async def deferred_sleep(delay: float) -> None:
            delays.append(delay)
            if len(delays) == 2:
                reservations_ready.set()
            await release_sleepers.wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            coordinator = AsyncRequestCoordinator(
                SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
                clock=lambda: 0.0,
                sleep=deferred_sleep,
            )
            sources = tuple(
                SemanticScholarRelevanceSearch(
                    client=client,
                    request_coordinator=coordinator,
                )
                for _ in range(3)
            )
            searches = asyncio.gather(
                *(source.search(LiteratureQuery("query", limit=1)) for source in sources)
            )
            await reservations_ready.wait()
            assert request_count == 1
            assert_floats_close(
                delays,
                [
                    SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
                    SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS * 2,
                ],
            )
            release_sleepers.set()
            await searches

    asyncio.run(run_searches())

    assert request_count == 3


def test_coordinator_uses_injected_monotonic_elapsed_time() -> None:
    clock = FakeMonotonicClock(now=100.0)
    coordinator = AsyncRequestCoordinator(
        SEMANTIC_SCHOLAR_MINIMUM_INTERVAL_SECONDS,
        clock=clock,
        sleep=clock.sleep,
    )

    async def acquire_twice() -> None:
        await coordinator.wait()
        clock.advance(0.4)
        await coordinator.wait()

    asyncio.run(acquire_twice())

    assert_floats_close(clock.delays, [0.7])
    assert isclose(clock(), 101.1)


def test_retry_backoff_and_request_coordinator_compose() -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        if len(request_starts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarBulkSearch(
                client=client,
                request_coordinator=isolated_coordinator(clock),
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
        clock = FakeMonotonicClock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = SemanticScholarRelevanceSearch(
                api_key,
                client,
                request_coordinator=isolated_coordinator(clock),
            )
            with pytest.raises(DiscoveryFailedError) as caught:
                await DiscoverSources(
                    (LiteratureSearchRequest(source, LiteratureQuery("safe query", limit=1)),)
                ).execute()
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
