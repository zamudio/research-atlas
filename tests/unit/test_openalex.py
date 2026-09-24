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
    LiteratureQuery,
    LiteratureSearchRequest,
)
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource


def test_openalex_maps_mocked_work_and_retries_rate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["search"] == "example topic"
        assert request.url.params["per_page"] == "5"
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
                            {"author": {"display_name": "Ada Author"}},
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
                LiteratureQuery("example topic", limit=5)
            )

    records = asyncio.run(run_search())

    assert calls == 2
    assert len(records) == 1
    record = records[0]
    assert record.title == "Example result"
    assert record.authors == ("Ada Author", "Ben Writer")
    assert record.year == 2022
    assert record.source_type == "article"
    assert record.source_url == "https://example.test/article"
    assert ("doi", "10.1000/example") in {
        (item.namespace, item.value) for item in record.external_identifiers
    }
    assert ("pmid", "42") in {(item.namespace, item.value) for item in record.external_identifiers}


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
