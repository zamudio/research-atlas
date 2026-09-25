import asyncio
from collections.abc import Callable

import httpx
import pytest

from research_atlas.application.discovery import DiscoverSources, serialize_report
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSearchRequest,
)
from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.studies import ExternalIdentifier, SourceRecord
from research_atlas.infrastructure.providers.crossref import CrossrefWorksSearch
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_atlas.infrastructure.providers.semantic_scholar import SemanticScholarRelevanceSearch


def search(
    handler: Callable[[httpx.Request], httpx.Response],
    query: LiteratureQuery | None = None,
    mailto: str | None = None,
) -> tuple[SourceRecord, ...]:
    async def run() -> tuple[SourceRecord, ...]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await CrossrefWorksSearch(mailto=mailto, client=client).search(
                query if query is not None else LiteratureQuery("exact bibliography", limit=5)
            )

    return asyncio.run(run())


def test_request_mapping_parameters_and_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["query.bibliographic"] == "exact bibliography"
        assert request.url.params["rows"] == "5"
        assert "cursor" not in request.url.params
        assert request.url.params["filter"] == "type:journal-article,from-pub-date:2020"
        assert request.url.params["sort"] == "relevance"
        assert request.url.params["mailto"] == "researcher@example.test"
        assert request.headers["user-agent"] == "ResearchAtlas/Crossref-feasibility"
        assert "authorization" not in request.headers
        assert "DOI" in request.url.params["select"].split(",")
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "https://doi.org/10.1000/EXAMPLE",
                            "title": [" Example title "],
                            "author": [
                                {"given": "Ada", "family": "Author"},
                                {"name": "Study Group"},
                                {"family": "Writer"},
                                {},
                            ],
                            "published": {"date-parts": [[2022, 3, 1]]},
                            "type": "journal-article",
                            "URL": "https://example.test/article",
                        }
                    ]
                }
            },
        )

    records = search(
        handler,
        LiteratureQuery(
            "exact bibliography",
            limit=5,
            parameters=(
                SearchParameter("filter", "type:journal-article"),
                SearchParameter("filter", "from-pub-date:2020"),
                SearchParameter("sort", "relevance"),
            ),
        ),
        mailto="researcher@example.test",
    )
    assert calls == 2
    record = records[0]
    assert record.title == "Example title"
    assert record.authors == ("Ada Author", "Study Group", "Writer")
    assert record.year == 2022
    assert record.source_type == "journal-article"
    assert record.source_url == "https://example.test/article"
    assert record.external_identifiers == (ExternalIdentifier("doi", "10.1000/example"),)
    provenance = record.provider_provenance[0]
    assert (provenance.provider, provenance.provider_record_id) == ("crossref", "10.1000/example")
    assert provenance.retrieved_at is not None and provenance.retrieved_at.utcoffset() is not None


@pytest.mark.parametrize(
    "name", ["query.bibliographic", "rows", "cursor", "select", "mailto", "offset", "sample"]
)
def test_reserved_parameters_fail_before_request(name: str) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("reserved parameters must fail before network access")

    with pytest.raises(ValueError, match="reserved parameters"):
        search(forbidden, LiteratureQuery("query", parameters=(SearchParameter(name, "value"),)))


def test_cursor_pagination_uses_new_token_and_stops_at_logical_limit() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = len(requests)
        assert request.url.params["cursor"] == ("*" if page == 1 else f"next-{page - 1}")
        assert request.url.params["rows"] == "100"
        assert request.url.params["filter"] == "type:journal-article"
        assert "mailto" not in request.url.params
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [{"DOI": f"10.1000/{page}-{i}"} for i in range(100)],
                    "next-cursor": f"next-{page}",
                }
            },
        )

    records = search(
        handler,
        LiteratureQuery(
            "query", limit=205, parameters=(SearchParameter("filter", "type:journal-article"),)
        ),
    )
    assert len(records) == 205
    assert len(requests) == 3
    assert records[-1].external_identifiers[0].value == "10.1000/3-4"


@pytest.mark.parametrize("sort", ["issued", "published", "published-print", "published-online"])
def test_cursor_incompatible_sort_fails_before_request(sort: str) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("incompatible cursor sort must fail before network access")

    with pytest.raises(ValueError, match="incompatible with required cursor pagination"):
        search(
            forbidden,
            LiteratureQuery("query", limit=101, parameters=(SearchParameter("sort", sort),)),
        )


def test_cursor_incompatible_sort_allows_single_page_without_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sort"] == "issued"
        assert "cursor" not in request.url.params
        return httpx.Response(200, json={"message": {"items": [{"DOI": "10.1000/example"}]}})

    assert (
        len(
            search(
                handler,
                LiteratureQuery(
                    "query", limit=100, parameters=(SearchParameter("sort", "issued"),)
                ),
            )
        )
        == 1
    )


@pytest.mark.parametrize(("count", "cursor"), [(0, "more"), (1, "more"), (100, None), (100, "")])
def test_short_page_or_absent_cursor_stops(count: int, cursor: str | None) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert calls == 1
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [{"DOI": f"10.1000/{i}"} for i in range(count)],
                    "next-cursor": cursor,
                }
            },
        )

    assert len(search(handler, LiteratureQuery("query", limit=101))) == count


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit_does_not_request(limit: int) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    assert search(forbidden, LiteratureQuery("query", limit=limit)) == ()


def test_missing_or_malformed_optional_metadata_remains_explicit() -> None:
    works: tuple[dict[str, object], ...] = (
        {"DOI": "10.1000/example"},
        {
            "DOI": "10.1000/example",
            "title": [None, 42],
            "author": [None, {"given": 42}],
            "published": {"date-parts": [[True]]},
            "created": {"date-parts": [[2020]]},
            "type": 42,
            "URL": 42,
        },
    )
    for work in works:
        response = httpx.Response(200, json={"message": {"items": [work]}})
        record = search(lambda _request, response=response: response)[0]
        assert record.title == ""
        assert record.authors == ()
        assert record.year is None
        assert record.source_type == "unknown"
        assert record.source_url is None


@pytest.mark.parametrize("field", ["published", "published-print", "published-online", "issued"])
def test_publication_year_fallbacks(field: str) -> None:
    response = httpx.Response(
        200,
        json={
            "message": {
                "items": [
                    {
                        "DOI": "10.1000/example",
                        field: {"date-parts": [[2021]]},
                    }
                ]
            }
        },
    )
    assert search(lambda _request: response)[0].year == 2021


INVALID_PAYLOADS: list[object] = [
    None,
    {},
    {"message": {}},
    {"message": {"items": {}}},
    {"message": {"items": [None]}},
    {"message": {"items": [{}]}},
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_invalid_response_fails_explicitly(payload: object) -> None:
    with pytest.raises(ValueError):
        search(lambda _request: httpx.Response(200, json=payload))


def test_discovery_merges_crossref_openalex_and_s2_by_exact_doi() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {"DOI": "10.1000/EXAMPLE", "title": ["Shared title"]},
                            {"DOI": "10.1000/different", "title": ["Shared title"]},
                        ]
                    }
                },
            )
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "doi": "https://doi.org/10.1000/example",
                        }
                    ]
                },
            )
        assert request.url.host == "api.semanticscholar.org"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "s2-1",
                        "externalIds": {"DOI": "10.1000/Example"},
                    }
                ]
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await DiscoverSources(
                [
                    LiteratureSearchRequest(source, LiteratureQuery("query", limit=2))
                    for source in (
                        CrossrefWorksSearch(client=client),
                        OpenAlexLiteratureSource(client=client),
                        SemanticScholarRelevanceSearch(client=client),
                    )
                ]
            ).execute()
        assert all(outcome.success for outcome in report.provider_outcomes)
        assert len(report.sources) == 2
        assert {p.provider for p in report.sources[0].provider_provenance} == {
            "crossref",
            "openalex",
            "semantic_scholar",
        }
        assert serialize_report(report)["cross_provider_merge_count"] == 1

    asyncio.run(run())
