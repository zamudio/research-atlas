import asyncio
from dataclasses import asdict
from typing import cast

import httpx
import pytest

import research_atlas.openalex as module
from research_atlas import Source
from research_atlas.embeddings import EmbeddingError
from research_atlas.openalex import OpenAlex, OpenAlexError
from tests.test_embeddings import FakeEmbedder
from tests.test_openalex import no_sleep


@pytest.fixture(autouse=True)
def unpaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_pace_semantic", lambda: no_sleep(0))


@pytest.mark.parametrize("empty", [False, True])
def test_successful_native_semantics_never_uses_embeddings_or_fallback(empty: bool) -> None:
    calls = 0
    embedder = FakeEmbedder(())

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert "search.semantic" in request.url.params
        assert "abstract_inverted_index" not in request.url.params["select"]
        return httpx.Response(
            200,
            json={
                "results": []
                if empty
                else [
                    {"has_content": {"grobid_xml": True, "pdf": True}, "id": "W2"},
                    {"has_content": {"grobid_xml": True, "pdf": True}, "id": "W1"},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources = await OpenAlex(client=client).search(
                "question", semantic=True, embedder=embedder
            )
            assert tuple(source.source.key for source in sources) == (() if empty else ("W2", "W1"))

    asyncio.run(scenario())
    assert calls == 1
    assert embedder.calls == []


@pytest.mark.parametrize("strategy", ["native", "fallback", "lexical"])
@pytest.mark.parametrize("eligible", [False, True])
def test_supported_routes_filter_before_ranking_and_preserve_native_order(
    strategy: str,
    eligible: bool,
) -> None:
    embedder = FakeEmbedder(((1, 0), (0, 1), (1, 0), (0, 1)))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.host == "api.openalex.org" and request.url.path == "/works"
        assert "filter" not in request.url.params
        fields = set(request.url.params["select"].split(","))
        assert {"id", "has_content", "best_oa_location", "primary_location", "locations"} <= fields
        if strategy == "fallback" and "search.semantic" in request.url.params:
            return httpx.Response(401)
        # This invalid abstract must never be constructed into ranking input.
        works: list[dict[str, object]] = [
            {"id": "W9", "title": "Unreadable", "abstract_inverted_index": {"bad": [-1]}},
            {"id": "W8", "has_content": {"grobid_xml": False, "pdf": False}},
            {
                "id": "W7",
                "best_oa_location": {"is_oa": True, "landing_page_url": "https://oa.test/landing"},
            },
            {"id": "W6", "locations": [{"is_oa": False, "pdf_url": "https://closed.test/pdf"}]},
        ]
        if eligible:
            works[1:1] = [
                {"id": "W3", "title": "GROBID", "has_content": {"grobid_xml": True}},
                {
                    "id": "W1",
                    "title": "OA",
                    "primary_location": {"is_oa": True, "pdf_url": "https://oa.test/pdf"},
                },
                {"id": "W2", "title": "PDF", "has_content": {"pdf": True}},
            ]
        return httpx.Response(200, json={"results": works})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search(
                "q",
                semantic=strategy != "lexical",
                embedder=embedder,
            )
            expected = ("W3", "W1", "W2") if strategy == "native" else ("W1", "W3", "W2")
            assert tuple(candidate.source.key for candidate in candidates) == (
                expected if eligible else ()
            )
            if eligible:
                routes = {candidate.source.key: candidate for candidate in candidates}
                assert (
                    routes["W3"].grobid_xml and not routes["W3"].pdf_urls and not routes["W3"].pdf
                )
                assert routes["W1"].pdf_urls == ("https://oa.test/pdf",)
                assert not routes["W1"].grobid_xml and not routes["W1"].pdf
                assert (
                    routes["W2"].pdf and not routes["W2"].grobid_xml and not routes["W2"].pdf_urls
                )

    asyncio.run(scenario())
    assert calls == (2 if strategy == "fallback" else 1)
    assert embedder.calls == (
        [("q", "GROBID", "OA", "PDF")] if strategy != "native" and eligible else []
    )


@pytest.mark.parametrize(
    "fault", ["lexical", "503", "429", "401", "transport", "empty", "malformed"]
)
def test_local_ranking_reaches_deep_lexical_candidates(fault: str) -> None:
    semantic_calls = 0
    lexical_calls = 0
    question = "  What improves learning?\n"
    embedder = FakeEmbedder(((1, 0), *((1, 0) if i == 47 else (0, 1) for i in range(50))))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal semantic_calls, lexical_calls
        if "search.semantic" in request.url.params:
            semantic_calls += 1
            assert lexical_calls == 0
            assert request.url.params["search.semantic"] == question
            if fault == "transport":
                raise httpx.ConnectError("private-key", request=request)
            if fault == "empty":
                return httpx.Response(200, content=b"")
            if fault == "malformed":
                return httpx.Response(200, content=b"{}")
            return httpx.Response(int(fault), headers={"Retry-After": "0"})
        lexical_calls += 1
        assert request.url.params["search"] == question
        assert request.url.params["per_page"] == "100"
        assert "abstract_inverted_index" in request.url.params["select"]
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "has_content": {"grobid_xml": True, "pdf": True},
                        "id": f"https://openalex.org/W{i + 1}",
                        "title": f"Title {i}",
                        "doi": f"https://doi.org/10.1234/WORK{i}",
                        "abstract_inverted_index": {"learning": [2], "Improved": [0], "later": [1]}
                        if i == 47
                        else None,
                    }
                    for i in range(50)
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources = await OpenAlex(client=client, retry_sleep=no_sleep).search(
                question,
                limit=50 if fault == "lexical" else 3,
                semantic=fault != "lexical",
                embedder=embedder,
            )
            expected_order = ("W48", *(f"W{i}" for i in range(1, 51) if i != 48))
            assert tuple(source.source.key for source in sources) == (
                expected_order if fault == "lexical" else expected_order[:3]
            )
            assert all(isinstance(source.source, Source) for source in sources)
            assert sources[0].source.doi == "10.1234/work47"
            assert set(asdict(sources[0].source)) == {
                "title",
                "authors",
                "year",
                "openalex_id",
                "doi",
                "url",
            }

    asyncio.run(scenario())
    assert semantic_calls == (
        0 if fault == "lexical" else 3 if fault in ("503", "429", "transport") else 1
    )
    assert lexical_calls == 1
    expected = tuple(
        "Title 47\n\nImproved later learning" if i == 47 else f"Title {i}" for i in range(50)
    )
    assert embedder.calls == [(question, *expected)]


def test_semantic_failure_without_embedder_preserves_explicit_provider_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert "search.semantic" in request.url.params
        return httpx.Response(503)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OpenAlexError, match="http_503"):
                await OpenAlex(client=client, retry_sleep=no_sleep).search("q", semantic=True)

    asyncio.run(scenario())
    assert calls == 3


@pytest.mark.parametrize("question", ["", " \n", "q" * 2001, None, 42])
def test_invalid_caller_input_never_triggers_fallback(question: object) -> None:
    embedder = FakeEmbedder(())
    with pytest.raises(ValueError, match="search query"):
        asyncio.run(OpenAlex().search(cast(str, question), semantic=True, embedder=embedder))
    assert embedder.calls == []


def test_lexical_search_failure_never_recurses_to_fallback() -> None:
    calls = 0
    embedder = FakeEmbedder(())

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OpenAlexError, match="http_401"):
                await OpenAlex(client=client).search("q", embedder=embedder)

    asyncio.run(scenario())
    assert calls == 1
    assert embedder.calls == []


@pytest.mark.parametrize("fault", ["lexical", "embedding", "abstract", "empty"])
def test_fallback_failures_propagate_and_empty_lexical_pool_is_valid(fault: str) -> None:
    embedder = FakeEmbedder(())

    def handler(request: httpx.Request) -> httpx.Response:
        if "search.semantic" in request.url.params:
            return httpx.Response(401)
        if fault == "lexical":
            return httpx.Response(403)
        if fault == "empty":
            return httpx.Response(200, json={"results": []})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "has_content": {"grobid_xml": True, "pdf": True},
                        "id": "W1",
                        "title": "Title",
                        "abstract_inverted_index": {"bad": [-1]} if fault == "abstract" else None,
                    }
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(client=client)
            if fault == "empty":
                assert await atlas.search("q", semantic=True, embedder=embedder) == ()
            else:
                with pytest.raises(EmbeddingError if fault == "embedding" else OpenAlexError):
                    await atlas.search("q", semantic=True, embedder=embedder)

    asyncio.run(scenario())
