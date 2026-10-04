import asyncio

import httpx
import pytest

import research_atlas.openalex as module
from research_atlas.openalex import OpenAlex
from tests.test_embeddings import FakeEmbedder
from tests.test_openalex import no_sleep

QUESTION = "Does spending time outside actually help people feel less stressed?"
SYNTAX = '*?~"\u201c\u201d\u201e\u201f()!|\\'


@pytest.mark.parametrize(
    "question,expected",
    [
        (QUESTION, QUESTION[:-1]),
        *((f"before{char}after", "before after") for char in SYNTAX),
        (f" \tbefore{SYNTAX}\n\t after\u00a0 ", "before after"),
        ("AND OR NOT ORCID CANDOR NOTABLE ANDROID", "and or not ORCID CANDOR NOTABLE ANDROID"),
        ("(AND) OR! NOT?", "and or not"),
        ("AND, OR: NOT.", "and, or: not."),
        ("and Or Not ORCID_AND", "and Or Not ORCID_AND"),
        (
            "well-being/stress isn't simple: e.g., people's health.",
            "well-being/stress isn't simple: e.g., people's health.",
        ),
    ],
)
def test_lexical_request_normalizes_only_query_syntax(question: str, expected: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["search"] == expected
        assert "search.semantic" not in request.url.params
        return httpx.Response(200, json={"results": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await OpenAlex(client=client).search(question) == ()

    asyncio.run(scenario())
    assert calls == 1


@pytest.mark.parametrize("strategy", ["lexical", "semantic", "fallback"])
def test_normalization_preserves_original_semantic_and_embedding_inputs(
    strategy: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_pace_semantic", lambda: no_sleep(0))
    question = f" \t{QUESTION} AND (OR NOT) {SYNTAX}\n"
    expected = f"{QUESTION[:-1]} and or not"
    embedder = FakeEmbedder(((1, 0), (0, 1), (1, 0)))
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "search.semantic" in request.url.params:
            requests.append("semantic")
            assert request.url.params["search.semantic"] == question
            assert "search" not in request.url.params
            if strategy == "fallback":
                return httpx.Response(401)
        else:
            requests.append("lexical")
            assert request.url.params["search"] == expected
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "W1", "title": "First", "has_content": {"pdf": True}},
                    {"id": "W2", "title": "Second", "has_content": {"pdf": True}},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search(
                question, semantic=strategy != "lexical", embedder=embedder
            )
            assert tuple(candidate.source.key for candidate in candidates) == (
                ("W1", "W2") if strategy == "semantic" else ("W2", "W1")
            )

    asyncio.run(scenario())
    assert (
        requests
        == {
            "lexical": ["lexical"],
            "semantic": ["semantic"],
            "fallback": ["semantic", "lexical"],
        }[strategy]
    )
    assert embedder.calls == ([] if strategy == "semantic" else [(question, "First", "Second")])


@pytest.mark.parametrize("question", ["?", SYNTAX, f" \t{SYNTAX}\n "])
@pytest.mark.parametrize("rank", [False, True])
def test_normalized_blank_lexical_query_fails_without_http(question: str, rank: bool) -> None:
    calls = 0
    embedder = FakeEmbedder(())

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"results": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError, match="lexical search query must be nonblank"):
                await OpenAlex(client=client).search(question, embedder=embedder if rank else None)

    asyncio.run(scenario())
    assert calls == 0
    assert embedder.calls == []


@pytest.mark.parametrize("fallback", [False, True])
def test_syntax_only_semantic_query_is_preserved_and_blank_fallback_is_local(
    fallback: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "_pace_semantic", lambda: no_sleep(0))
    calls = 0
    embedder = FakeEmbedder(())

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["search.semantic"] == SYNTAX
        assert "search" not in request.url.params
        return httpx.Response(401) if fallback else httpx.Response(200, json={"results": []})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(client=client)
            if fallback:
                with pytest.raises(ValueError, match="lexical search query must be nonblank"):
                    await atlas.search(SYNTAX, semantic=True, embedder=embedder)
            else:
                assert await atlas.search(SYNTAX, semantic=True, embedder=embedder) == ()

    asyncio.run(scenario())
    assert calls == 1
    assert embedder.calls == []
