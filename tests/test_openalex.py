import asyncio

import httpx
import pytest

from conftest import MockHTTP
from research_atlas.config import Settings
from research_atlas.openalex import discover


def test_one_semantic_request_qualifies_advertised_routes_in_order(
    mock_http: MockHTTP, settings: Settings
) -> None:
    question = '  Does "outside" reduce stress?  '
    calls: list[httpx.Request] = []
    records: list[dict[str, object]] = [
        {
            "id": "https://openalex.org/W3",
            "title": "First",
            "publication_year": 2024,
            "doi": "https://doi.org/10.1234/example",
            "has_content": {"grobid_xml": True, "pdf": True},
            "best_oa_location": {"is_oa": True, "pdf_url": "https://oa.test/first"},
            "primary_location": {"is_oa": True, "pdf_url": "https://oa.test/first"},
            "locations": [
                {"is_oa": False, "pdf_url": "https://closed.test/paper"},
                {"is_oa": True, "pdf_url": "http://127.0.0.1/paper"},
                {"is_oa": True, "pdf_url": "https://oa.test/second"},
            ],
        },
        {
            "id": "W4",
            "doi": "https://doi.org/10.1234/only-doi",
            "primary_location": {"landing_page_url": "https://oa.test/landing"},
            "abstract_inverted_index": {"stress": [0]},
            "has_fulltext": True,
        },
        {"id": "W5", "locations": [{"is_oa": True, "pdf_url": "https://oa.test/fifth"}]},
        {"id": "W6", "has_content": {"pdf": True}},
        {"id": "W3", "has_content": {"pdf": True}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/works"
        assert request.url.params["search.semantic"] == question
        assert request.url.params["filter"] == "has_fulltext:true"
        assert request.url.params["per_page"] == "50"
        assert set(request.url.params["select"].split(",")) == {
            "id",
            "title",
            "doi",
            "publication_year",
            "has_content",
            "best_oa_location",
            "primary_location",
            "locations",
        }
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert "api_key" not in request.url.params
        return httpx.Response(200, json={"results": records, "meta": {"count": 999}})

    mock_http(handler)

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            works, failures = await discover(question, client, settings)
        assert [work.openalex_id for work in works] == ["W3", "W5", "W6"]
        assert [route.kind for route in works[0].routes] == [
            "grobid_xml",
            "oa_pdf",
            "oa_pdf",
            "openalex_pdf",
        ]
        assert [route.url for route in works[0].routes] == [
            "https://content.openalex.org/works/W3.grobid-xml",
            "https://oa.test/first",
            "https://oa.test/second",
            "https://content.openalex.org/works/W3.pdf",
        ]
        assert works[0].year == 2024 and works[0].doi == "https://doi.org/10.1234/example"
        assert not failures

    asyncio.run(run())
    assert len(calls) == 1


def test_malformed_work_does_not_discard_other_results(
    mock_http: MockHTTP, settings: Settings
) -> None:
    mock_http(
        lambda _: httpx.Response(
            200,
            json={
                "results": [
                    {"id": "W1", "publication_year": "wrong", "has_content": {"pdf": True}},
                    {"id": "not-a-work", "has_content": {"grobid_xml": True}},
                    {"id": "W2", "has_content": {"pdf": True}},
                ]
            },
        )
    )

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            works, failures = await discover("stress", client, settings)
        assert [work.openalex_id for work in works] == ["W2"]
        assert len(failures) == 2 and all(item.stage == "discovery" for item in failures)
        assert failures[0].openalex_id == "W1"

    asyncio.run(run())


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": "wrong"}])
def test_invalid_envelope_is_fatal(
    payload: dict[str, object], mock_http: MockHTTP, settings: Settings
) -> None:
    mock_http(lambda _: httpx.Response(200, json=payload))

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                await discover("stress", client, settings)

    asyncio.run(run())


def test_discovery_caps_even_an_oversized_response(mock_http: MockHTTP, settings: Settings) -> None:
    mock_http(
        lambda _: httpx.Response(
            200,
            json={
                "results": [{"id": f"W{i}", "has_content": {"pdf": True}} for i in range(1, 101)]
            },
        )
    )

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            works, _ = await discover("stress", client, settings)
        assert len(works) == 50 and works[-1].openalex_id == "W50"

    asyncio.run(run())
