import asyncio

import httpx

from research_atlas.application.ports.literature_source import LiteratureQuery
from research_atlas.infrastructure.providers.semantic_scholar import (
    SemanticScholarLiteratureSource,
)


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
                LiteratureQuery("feedback", limit=5)
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
