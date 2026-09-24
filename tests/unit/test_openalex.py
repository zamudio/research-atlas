import asyncio

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource


def test_openalex_maps_mocked_work_and_retries_rate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/works"
        assert request.url.params["search"] == "formative feedback"
        assert request.url.params["per_page"] == "5"
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "doi": "https://doi.org/10.1000/EXAMPLE",
                        "title": "Feedback works",
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
                LiteratureQuery("formative feedback", limit=5)
            )

    records = asyncio.run(run_search())

    assert calls == 2
    assert len(records) == 1
    record = records[0]
    assert record.title == "Feedback works"
    assert record.authors == ("Ada Author", "Ben Writer")
    assert record.year == 2022
    assert record.source_type == "article"
    assert record.source_url == "https://example.test/article"
    assert ("doi", "10.1000/example") in {
        (item.namespace, item.value) for item in record.external_identifiers
    }
    assert ("pmid", "42") in {(item.namespace, item.value) for item in record.external_identifiers}
