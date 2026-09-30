import asyncio
import json

import httpx
import pytest

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureBatch,
    LiteratureQuery,
    LiteratureSearchRequest,
)
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.execution import SearchParameter
from research_atlas.infrastructure.providers import openalex
from research_atlas.infrastructure.providers.openalex import (
    OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS,
    OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS,
    OpenAlexLiteratureSource,
    OpenAlexSemanticRequestCoordinator,
    OpenAlexSemanticSearch,
)


class FakeMonotonicClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


def isolated_semantic_coordinator(
    clock: FakeMonotonicClock,
) -> OpenAlexSemanticRequestCoordinator:
    return OpenAlexSemanticRequestCoordinator(
        OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS,
        clock=clock,
        sleep=clock.sleep,
    )


def test_openalex_maps_mocked_work_and_retries_rate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["search"] == "example topic"
        assert request.url.params["per_page"] == "5"
        assert request.url.params["filter"] == "type:review"
        assert "authorization" not in request.headers
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.1000/EXAMPLE",
                        "title": "Example result",
                        "authorships": [
                            {
                                "raw_author_name": "A. Author",
                                "raw_orcid": "https://orcid.org/0000-0002-1694-233X",
                                "author": {
                                    "id": "https://openalex.org/A123",
                                    "display_name": "Ada Author",
                                    "orcid": "https://orcid.org/0000-0002-1825-0097",
                                },
                            },
                            {"author": {"display_name": "Ben Writer"}},
                        ],
                        "publication_year": 2022,
                        "publication_date": "2022-02-03",
                        "type": "article",
                        "primary_location": {
                            "landing_page_url": "https://example.test/article",
                            "source": {"type": "journal"},
                        },
                        "ids": {
                            "openalex": "https://openalex.org/W123",
                            "doi": "https://doi.org/10.1000/EXAMPLE",
                            "pmid": "https://pubmed.ncbi.nlm.nih.gov/42",
                        },
                    }
                ],
                "meta": {"next_cursor": None},
            },
        )

    async def run_search():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.openalex.org"
        ) as client:
            return await OpenAlexLiteratureSource(client=client).search(
                LiteratureQuery(
                    "example topic",
                    limit=5,
                    parameters=(SearchParameter("filter", "type:review"),),
                )
            )

    records = asyncio.run(run_search()).records

    assert calls == 2
    assert len(records) == 1
    literature_record = records[0]
    record = literature_record.source
    assert record.title == "Example result"
    assert record.authors == ("A. Author", "Ben Writer")
    assert record.year == 2022
    assert record.source_type == "article"
    assert record.source_url == "https://example.test/article"
    assert ("doi", "https://doi.org/10.1000/EXAMPLE") in {
        (item.namespace, item.value) for item in record.external_identifiers
    }
    assert ("pmid", "https://pubmed.ncbi.nlm.nih.gov/42") in {
        (item.namespace, item.value) for item in record.external_identifiers
    }
    assert literature_record.credits == (
        BibliographicCredit(
            "A. Author",
            provider_record_id="A123",
            external_identifiers=(("orcid", "https://orcid.org/0000-0002-1825-0097"),),
        ),
        BibliographicCredit("Ben Writer"),
    )
    provenance = record.provider_provenance[0]
    assert provenance.provider_record_id == "W123"
    assert provenance.retrieved_at is not None and provenance.retrieved_at.utcoffset() is not None


def test_authenticated_openalex_uses_bearer_header_without_key_in_request_data() -> None:
    api_key = "sensitive-openalex-key"
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"results": [], "meta": {"next_cursor": None}})

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await OpenAlexLiteratureSource(api_key, client).search(
                LiteratureQuery("safe query", limit=1)
            )

    asyncio.run(run_search())

    assert captured_request is not None
    assert captured_request.headers["authorization"] == f"Bearer {api_key}"
    assert "api_key" not in captured_request.url.params
    assert api_key not in str(captured_request.url)
    assert api_key not in captured_request.content.decode()


def test_openalex_provider_error_is_sanitized() -> None:
    api_key = "sensitive-openalex-error-key"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async def run_discovery() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = OpenAlexLiteratureSource(api_key, client)
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


def test_openalex_semantic_uses_exact_mode_forwards_parameters_and_preserves_order() -> None:
    exact_query = " How do feedback loops affect student learning? "
    work_ids = ("W3", "W1", "W2")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["search.semantic"] == exact_query
        assert "search" not in request.url.params
        assert "search.exact" not in request.url.params
        assert "cursor" not in request.url.params
        assert request.url.params["per_page"] == "50"
        assert request.url.params["filter"] == "type:article"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"https://openalex.org/{work_id}",
                        "doi": f"https://doi.org/10.1000/{work_id}",
                        "title": f"Result {work_id}",
                        "authorships": [{"author": {"display_name": "Ada Author"}}],
                        "publication_year": 2024,
                        "type": "article",
                        "primary_location": {"landing_page_url": f"https://example.test/{work_id}"},
                        "ids": {"pmid": f"https://pubmed.ncbi.nlm.nih.gov/{work_id[1:]}"},
                    }
                    for work_id in work_ids
                ]
            },
        )

    async def run_search() -> LiteratureBatch:
        clock = FakeMonotonicClock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = OpenAlexSemanticSearch(
                client=client,
                request_coordinator=isolated_semantic_coordinator(clock),
            )
            assert source.provider_id == "openalex"
            assert source.operation_id == "openalex.semantic"
            return await source.search(
                LiteratureQuery(
                    exact_query,
                    limit=50,
                    parameters=(SearchParameter("filter", "type:article"),),
                )
            )

    records = asyncio.run(run_search()).records

    assert calls == 1
    assert [record.source.title for record in records] == [
        f"Result {work_id}" for work_id in work_ids
    ]
    assert [record.source.provider_provenance[0].provider_record_id for record in records] == list(
        work_ids
    )
    assert records[0].source.authors == ("Ada Author",)
    assert records[0].source.year == 2024
    assert records[0].source.source_type == "article"
    assert records[0].source.source_url == "https://example.test/W3"
    assert {(item.namespace, item.value) for item in records[0].source.external_identifiers} == {
        ("doi", "https://doi.org/10.1000/W3"),
        ("openalex", "W3"),
        ("pmid", "https://pubmed.ncbi.nlm.nih.gov/3"),
    }


def test_openalex_semantic_rejects_limit_above_50_before_network_access() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("limit validation must happen before network access")

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="at most 50 results"):
                await OpenAlexSemanticSearch(client=client).search(
                    LiteratureQuery("semantic question", limit=51)
                )

    asyncio.run(run_search())

    assert calls == 0


def test_openalex_semantic_default_coordinator_is_shared_across_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []
    monkeypatch.setattr(
        openalex,
        "_DEFAULT_SEMANTIC_REQUEST_COORDINATOR",
        isolated_semantic_coordinator(clock),
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        return httpx.Response(200, json={"results": []})

    async def run_searches() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first_source = OpenAlexSemanticSearch(client=client)
            second_source = OpenAlexSemanticSearch(client=client)
            await asyncio.gather(
                first_source.search(LiteratureQuery("first semantic query", limit=1)),
                second_source.search(LiteratureQuery("second semantic query", limit=1)),
            )

    asyncio.run(run_searches())

    assert request_starts == [0.0, OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS]
    assert clock.delays == [OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS]


def test_openalex_semantic_retries_are_paced() -> None:
    clock = FakeMonotonicClock()
    request_starts: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        request_starts.append(clock())
        if len(request_starts) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"results": []})

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await OpenAlexSemanticSearch(
                client=client,
                request_coordinator=isolated_semantic_coordinator(clock),
                retry_sleep=clock.sleep,
            ).search(LiteratureQuery("retry semantic query", limit=1))

    asyncio.run(run_search())

    assert request_starts == [0.0, OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS]
    assert clock.delays == [0.5, OPENALEX_SEMANTIC_MINIMUM_INTERVAL_SECONDS - 0.5]


def test_openalex_lexical_search_is_not_semantically_paced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeMonotonicClock()
    request_starts: list[tuple[str, float]] = []
    monkeypatch.setattr(
        openalex,
        "_DEFAULT_SEMANTIC_REQUEST_COORDINATOR",
        isolated_semantic_coordinator(clock),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        operation = "semantic" if "search.semantic" in request.url.params else "lexical"
        request_starts.append((operation, clock()))
        payload: dict[str, object] = {"results": []}
        if operation == "lexical":
            payload["meta"] = {"next_cursor": None}
        return httpx.Response(200, json=payload)

    async def run_searches() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await OpenAlexSemanticSearch(client=client).search(
                LiteratureQuery("semantic query", limit=1)
            )
            await OpenAlexLiteratureSource(client=client).search(
                LiteratureQuery("lexical query", limit=1)
            )

    asyncio.run(run_searches())

    assert request_starts == [("semantic", 0.0), ("lexical", 0.0)]
    assert clock.delays == []


def test_openalex_semantic_accepts_exactly_2000_characters_without_rewriting() -> None:
    exact_query = " q " + "x" * (OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS - 3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["search.semantic"] == exact_query
        return httpx.Response(200, json={"results": []})

    async def run_search() -> None:
        clock = FakeMonotonicClock()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await OpenAlexSemanticSearch(
                client=client,
                request_coordinator=isolated_semantic_coordinator(clock),
            ).search(LiteratureQuery(exact_query, limit=1))

    asyncio.run(run_search())

    assert len(exact_query) == OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS
    assert calls == 1


def test_openalex_semantic_rejects_2001_characters_before_network_access() -> None:
    too_long_query = "x" * (OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS + 1)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("query length validation must happen before network access")

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="at most 2,000 characters"):
                await OpenAlexSemanticSearch(client=client).search(
                    LiteratureQuery(too_long_query, limit=1)
                )

    asyncio.run(run_search())

    assert len(too_long_query) == OPENALEX_SEMANTIC_MAXIMUM_QUERY_CHARACTERS + 1
    assert calls == 0


@pytest.mark.parametrize(
    "name",
    ("cursor", "per_page", "search", "search.exact", "search.semantic", "select"),
)
def test_openalex_semantic_rejects_adapter_owned_parameters(name: str) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("reserved-parameter validation must happen before network access")

    async def run_search() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="manages reserved parameters"):
                await OpenAlexSemanticSearch(client=client).search(
                    LiteratureQuery(
                        "semantic question",
                        parameters=(SearchParameter(name, "override"),),
                    )
                )

    asyncio.run(run_search())

    assert calls == 0
