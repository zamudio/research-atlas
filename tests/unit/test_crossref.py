import asyncio
from collections.abc import Callable

import httpx
import pytest

from research_atlas.application.discovery import DiscoverSources, serialize_report
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureRecord,
    LiteratureSearchRequest,
    LiteratureSourceError,
)
from research_atlas.domain.contributors import BibliographicCredit
from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.studies import ExternalIdentifier
from research_atlas.infrastructure.providers.crossref import CrossrefWorksSearch
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource


def search(
    handler: Callable[[httpx.Request], httpx.Response],
    query: LiteratureQuery | None = None,
    mailto: str | None = None,
) -> tuple[LiteratureRecord, ...]:
    async def run() -> tuple[LiteratureRecord, ...]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return (
                await CrossrefWorksSearch(mailto=mailto, client=client).search(
                    query if query is not None else LiteratureQuery("exact bibliography", limit=5)
                )
            ).records

    return asyncio.run(run())


def test_request_mapping_parameters_and_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["query.bibliographic"] == "exact bibliography"
        assert request.url.params["rows"] == "5"
        assert request.url.params["cursor"] == "*"
        assert request.url.params["filter"] == "type:journal-article,from-pub-date:2020"
        assert request.url.params["sort"] == "relevance"
        assert request.url.params["mailto"] == "researcher@example.test"
        assert request.headers["user-agent"] == "ResearchAtlas"
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
                                {
                                    "given": "Ada",
                                    "family": "Author",
                                    "ORCID": "https://orcid.org/0000-0002-1825-0097",
                                },
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
    literature_record = records[0]
    record = literature_record.source
    assert record.title == "Example title"
    assert record.authors == ("Ada Author", "Study Group", "Writer", "")
    assert record.year == 2022
    assert record.source_type == "journal-article"
    assert record.source_url == "https://example.test/article"
    assert record.external_identifiers == (
        ExternalIdentifier("doi", "https://doi.org/10.1000/EXAMPLE"),
    )
    provenance = record.provider_provenance[0]
    assert (provenance.provider, provenance.provider_record_id) == ("crossref", "10.1000/example")
    assert provenance.retrieved_at is not None and provenance.retrieved_at.utcoffset() is not None
    assert literature_record.credits == (
        BibliographicCredit(
            "Ada Author", external_identifiers=(("orcid", "https://orcid.org/0000-0002-1825-0097"),)
        ),
        BibliographicCredit("Study Group"),
        BibliographicCredit("Writer"),
        BibliographicCredit(""),
    )


@pytest.mark.parametrize(
    "name", ["query.bibliographic", "rows", "cursor", "select", "mailto", "offset", "sample"]
)
def test_reserved_parameters_fail_before_request(name: str) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("reserved parameters must fail before network access")

    with pytest.raises(ValueError, match="reserved parameters"):
        search(forbidden, LiteratureQuery("query", parameters=(SearchParameter(name, "value"),)))


@pytest.mark.parametrize("sort", ["issued", "published", "published-print", "published-online"])
def test_cursor_incompatible_sort_fails_before_request(sort: str) -> None:
    def forbidden(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("incompatible cursor sort must fail before network access")

    with pytest.raises(ValueError, match="incompatible with cursor pagination"):
        search(
            forbidden,
            LiteratureQuery("query", limit=100, parameters=(SearchParameter("sort", sort),)),
        )


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_invalid_batch_limit_is_rejected(limit: int) -> None:
    with pytest.raises(ValueError, match="batch limit"):
        LiteratureQuery("query", limit=limit)


def test_missing_optional_metadata_remains_unknown() -> None:
    record = search(
        lambda _request: httpx.Response(
            200, json={"message": {"items": [{"DOI": "10.1000/example"}]}}
        )
    )[0].source
    assert (record.title, record.authors, record.year, record.source_type, record.source_url) == (
        "",
        (),
        None,
        "unknown",
        None,
    )


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
    assert search(lambda _request: response)[0].source.year == 2021


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
    with pytest.raises(LiteratureSourceError, match="malformed response"):
        search(lambda _request: httpx.Response(200, json=payload))


def test_discovery_merges_crossref_and_openalex_by_exact_doi() -> None:
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
                    "meta": {"next_cursor": None},
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "doi": "https://doi.org/10.1000/example",
                        }
                    ],
                },
            )
        raise AssertionError("unexpected provider")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await DiscoverSources(
                [
                    LiteratureSearchRequest(source, LiteratureQuery("query", limit=3))
                    for source in (
                        CrossrefWorksSearch(client=client),
                        OpenAlexLiteratureSource(client=client),
                    )
                ]
            ).execute()
        assert all(outcome.status == "succeeded" for outcome in report.provider_outcomes)
        assert len(report.sources) == 2
        assert {p.provider for p in report.sources[0].provider_provenance} == {
            "crossref",
            "openalex",
        }
        assert serialize_report(report)["cross_provider_merge_count"] == 1

    asyncio.run(run())


def test_unverified_credit_identifiers_do_not_block_source_mapping() -> None:
    payload = {
        "message": {
            "items": [
                {
                    "DOI": "10.1000/example",
                    "author": [{"name": "Study Group", "ORCID": "provider-supplied-invalid-orcid"}],
                }
            ]
        }
    }
    record = search(lambda _request: httpx.Response(200, json=payload))[0]
    assert record.credits[0].external_identifiers == (("orcid", "provider-supplied-invalid-orcid"),)
    assert record.source.authors == ("Study Group",)
