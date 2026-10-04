# Transport-policy tests intentionally exercise the private HTTP boundary.
# pyright: reportPrivateUsage=false
import asyncio
import gzip
from collections.abc import AsyncIterator
from dataclasses import asdict

import httpx
import pytest
from pydantic import SecretStr

import research_atlas.openalex as module
from research_atlas import Source
from research_atlas.embeddings import EmbeddingError
from research_atlas.openalex import ContentCandidate, OpenAlex, OpenAlexError
from tests.test_embeddings import FakeEmbedder
from tests.test_extraction import SOURCE, XML

KEY = SecretStr("private-key")


async def no_sleep(_: float) -> None:
    pass


def test_search_maps_ordered_citations_and_normalized_scholarly_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.params["search"] == "learning"
        assert request.url.params["per_page"] == "100"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert "private-key" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "has_content": {"grobid_xml": True},
                        "doi": "https://doi.org/10.1234/ABC",
                        "title": "Learning",
                        "publication_year": 2024,
                        "authorships": [
                            {"raw_author_name": "First"},
                            {"author": {"display_name": "Second"}},
                        ],
                        "primary_location": {"landing_page_url": "https://example.org/paper"},
                        "unused": "ignored",
                    },
                    {"id": "W456", "has_content": {"pdf": True}},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(KEY, client)
            sources = await atlas.search("learning", limit=2)
            assert sources[0].source.key == "W123"
            assert sources[0].source.doi == "10.1234/abc"
            assert sources[0].source.openalex_id == "W123"
            assert sources[0].source.authors == ("First", "Second")
            assert sources[0].source.url == "https://example.org/paper"
            assert sources[1].source.key == "W456"
            assert "private-key" not in repr(atlas)
            assert set(asdict(sources[0].source)) == {
                "title",
                "authors",
                "year",
                "openalex_id",
                "doi",
                "url",
            }

    asyncio.run(scenario())


@pytest.mark.parametrize("identity", ["w123", " https://openalex.org/W123/ ", "W123"])
def test_source_openalex_normalization(identity: str) -> None:
    assert Source("", (), None, identity).key == "W123"


@pytest.mark.parametrize("identity", ["", "W0", "W-1", "https://evil.test/W123", "W123?key=x"])
def test_source_rejects_invalid_work_ids(identity: str) -> None:
    with pytest.raises(ValueError):
        Source("", (), None, identity)


@pytest.mark.parametrize("doi", ["https://doi.org/10.1234/ABC", "DOI:10.1234/abc", "10.1234/abc"])
def test_doi_is_citation_metadata_only(doi: str) -> None:
    source = Source("", (), None, "https://openalex.org/W123", doi)
    assert source.key == "W123"
    assert source.doi == "10.1234/abc"


def test_semantic_request_uses_provider_ranking_and_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    waits = 0

    async def pace() -> None:
        nonlocal waits
        waits += 1

    monkeypatch.setattr(module, "_pace_semantic", pace)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search.semantic"] == "learning"
        assert "search" not in request.url.params and "cursor" not in request.url.params
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "W2", "has_content": {"pdf": True}},
                    {"id": "W1", "has_content": {"pdf": True}},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources = await OpenAlex(client=client).search("learning", semantic=True)
            assert [source.source.key for source in sources] == ["W2", "W1"]

    asyncio.run(scenario())
    assert waits == 1


@pytest.mark.parametrize(
    "query,limit,semantic",
    [
        (" ", 1, False),
        ("x" * 2001, 1, False),
        ("q", 0, False),
        ("q", module.DISCOVERY_POOL_SIZE + 1, False),
        ("q", 51, True),
        ("q", True, False),
    ],
)
def test_search_input_bounds(query: str, limit: int, semantic: bool) -> None:
    with pytest.raises(ValueError):
        asyncio.run(OpenAlex().search(query, limit=limit, semantic=semantic))


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"{}",
        b'{"results":[{"id":"invalid"}]}',
        b'{"results":[{"id":"W1","publication_year":"2024"}]}',
        b'{"results":[' + b",".join([b'{"id":"W1"}'] * 101) + b"]}",
    ],
)
def test_search_invalid_response_is_safe(body: bytes) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
        ) as client:
            with pytest.raises(OpenAlexError, match="malformed_search_response"):
                await OpenAlex(client=client).search("q", limit=1)

    asyncio.run(scenario())


@pytest.mark.parametrize("compressed", [False, True])
def test_content_returns_exact_decoded_xml(compressed: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openalex.org":
            assert request.url.path == "/works"
            return httpx.Response(
                200, json={"results": [{"id": SOURCE.key, "has_content": {"grobid_xml": True}}]}
            )
        assert str(request.url) == "https://content.openalex.org/works/W123.grobid-xml"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 20
        )
        return httpx.Response(
            200,
            content=gzip.compress(XML) if compressed else XML,
            headers={"Content-Encoding": "gzip"} if compressed else {},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(KEY, client)
            candidates = await atlas.search("learning")
            result = await atlas.fetch_content(candidates[0])
            assert result is not None and result.original == XML and result.kind == "grobid"

    asyncio.run(scenario())


@pytest.mark.parametrize("code", [301, 401, 403, 404, 429, 500])
def test_content_status_and_retry_policy(code: int) -> None:
    calls = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            code,
            text="private-key remote body",
            headers={"Location": "https://evil.test", "Retry-After": "999999"},
        )

    async def sleep(delay: float) -> None:
        delays.append(delay)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            atlas = OpenAlex(KEY, client, retry_sleep=sleep)
            if code == 404:
                assert (
                    await atlas._get(
                        "https://content.openalex.org/works/W123.grobid-xml",
                        bound=1024,
                        allow_missing=True,
                    )
                    is None
                )
            else:
                with pytest.raises(OpenAlexError) as error:
                    await atlas._get(
                        "https://content.openalex.org/works/W123.grobid-xml",
                        bound=1024,
                        allow_missing=True,
                    )
                assert str(error.value) == f"http_{code}"

    asyncio.run(scenario())
    assert calls == (3 if code in (429, 500) else 1)
    assert delays == ([20, 20] if calls == 3 else [])


@pytest.mark.parametrize("body", [b"not XML", b"<TEI", b"<TEI/>", b"<!DOCTYPE a><a/>"])
def test_transport_returns_bytes_without_xml_validation(body: bytes) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
        ) as client:
            assert (
                await OpenAlex(KEY, client)._get(
                    "https://content.openalex.org/works/W123.grobid-xml", bound=1024
                )
                == body
            )

    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["transport", "timeout", "empty", "size"])
def test_content_safety_and_bounds(fault: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    monkeypatch.setattr(module, "MAX_CONTENT_BYTES", 256)

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * 200
            yield b"x" * 200

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fault == "transport":
            raise httpx.ConnectError("private-key", request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout("private-key", request=request)
        if fault == "size":
            return httpx.Response(200, stream=Chunks())
        return httpx.Response(200, content=b"")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OpenAlexError) as error:
                await OpenAlex(KEY, client, retry_sleep=no_sleep)._get(
                    "https://content.openalex.org/works/W123.grobid-xml", bound=256
                )
            assert "private-key" not in str(error.value)
            assert error.value.__cause__ is None

    asyncio.run(scenario())
    assert calls == (3 if fault in ("transport", "timeout") else 1)


def test_missing_content_credential_fails_before_io() -> None:
    with pytest.raises(OpenAlexError, match="missing_api_key"):
        asyncio.run(OpenAlex().fetch_content(ContentCandidate(SOURCE, True, (), False)))


@pytest.mark.parametrize(
    "url",
    [
        "https://oa.test/paper.pdf",
        "http://127.0.0.1/pdf",
        "http://localhost/pdf",
        "https://user:secret@oa.test/pdf",
        "file:///paper.pdf",
        "http://[",
        "https://oa.test:bad/pdf",
    ],
)
def test_oa_only_eligibility_requires_public_pdf_url(url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works" and "filter" not in request.url.params
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "W123",
                        "has_content": {"grobid_xml": False, "pdf": False},
                        "best_oa_location": {"is_oa": True, "pdf_url": url},
                    }
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search("q")
            assert len(candidates) == (1 if url == "https://oa.test/paper.pdf" else 0)

    asyncio.run(scenario())


@pytest.mark.parametrize("embedding_failure", [False, True])
def test_lexical_ranking_filters_before_embedding_and_filling_final_slots(
    embedding_failure: bool,
) -> None:
    requests: list[httpx.Request] = []
    texts = ("Early", "Deep\n\nRelevant abstract")
    embedder = FakeEmbedder(() if embedding_failure else ((1, 0), (0, 1), (1, 0)))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/works" and request.url.params["search"] == "q"
        assert "search.semantic" not in request.url.params
        assert request.url.params["per_page"] == "100"
        assert "filter" not in request.url.params
        assert {
            "id",
            "title",
            "doi",
            "publication_year",
            "authorships",
            "primary_location",
            "has_content",
            "best_oa_location",
            "locations",
            "abstract_inverted_index",
        } <= set(request.url.params["select"].split(","))
        assert "page" not in request.url.params and "cursor" not in request.url.params
        works: list[dict[str, object]] = [
            {"id": f"W{i}", "title": "Unreadable", "abstract_inverted_index": {"bad": [-1]}}
            for i in range(1, 51)
        ]
        works[1] = {"id": "W2", "title": "Early", "has_content": {"grobid_xml": True}}
        works[47] = {
            "id": "W48",
            "title": "Deep",
            "has_content": {"pdf": True},
            "abstract_inverted_index": {"abstract": [1], "Relevant": [0]},
        }
        works[49] = {
            "id": "W50",
            "title": "Last",
            "locations": [{"is_oa": True, "pdf_url": "https://oa.test/paper.pdf"}],
        }
        return httpx.Response(200, json={"results": works})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search("q", limit=2, embedder=embedder)
            assert tuple(candidate.source.key for candidate in candidates) == (
                ("W2", "W48") if embedding_failure else ("W48", "W2")
            )

    asyncio.run(scenario())
    assert len(requests) == 1
    assert embedder.calls == [("q", *texts)]


@pytest.mark.parametrize("error", [ValueError("bug"), RuntimeError("bug")])
def test_lexical_ranking_unrelated_errors_propagate(error: Exception) -> None:
    class BrokenEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            raise error

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"results": [{"id": "W1", "has_content": {"pdf": True}}]}
                )
            )
        ) as client:
            with pytest.raises(type(error)) as raised:
                await OpenAlex(client=client).search("q", embedder=BrokenEmbedder())
            assert raised.value is error

    asyncio.run(scenario())


def test_lexical_recoverable_embedding_failure_preserves_eligible_order() -> None:
    class UnavailableEmbedder:
        async def embed(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            assert texts == ("q", "First", "Second")
            raise EmbeddingError("ollama_embedding_transport_failure")

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "results": [
                            {"id": "W9", "title": "Unavailable"},
                            {"id": "W2", "title": "First", "has_content": {"pdf": True}},
                            {"id": "W1", "title": "Second", "has_content": {"grobid_xml": True}},
                        ]
                    },
                )
            )
        ) as client:
            candidates = await OpenAlex(client=client).search("q", embedder=UnavailableEmbedder())
            assert tuple(candidate.source.key for candidate in candidates) == ("W2", "W1")

    asyncio.run(scenario())


@pytest.mark.parametrize("ranking", ["local", "fallback", "provider"])
@pytest.mark.parametrize(
    "eligible_positions,total_works",
    [
        (tuple(range(1, 101)), 100),
        (tuple(range(51, 101)), 100),
        (tuple(range(1, 26)) + tuple(range(51, 101)), 100),
        ((2, 51, 99, 100), 100),
        ((51, 52, 63), 63),
        ((), 100),
    ],
    ids=["full-pool", "deep-pool", "surplus-eligible", "partial-pool", "short-response", "none"],
)
def test_one_discovery_pool_retains_only_eligible_ranking_candidates(
    ranking: str,
    eligible_positions: tuple[int, ...],
    total_works: int,
) -> None:
    expected = eligible_positions[: module.DEFAULT_ELIGIBLE_POOL_TARGET]
    texts = tuple(f"Paper {position}" for position in expected)
    embedder = FakeEmbedder(
        ()
        if ranking == "fallback"
        else ((1, 0), *((1, 0) if position == expected[-1] else (0, 1) for position in expected))
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert requests == 1
        assert request.url.host == "api.openalex.org" and request.url.path == "/works"
        assert request.url.params["search"] == "q"
        assert request.url.params["per_page"] == "100"
        assert "page" not in request.url.params and "cursor" not in request.url.params
        assert "search.semantic" not in request.url.params and "filter" not in request.url.params
        fields = set(request.url.params["select"].split(","))
        assert {"has_content", "locations"} <= fields
        assert ("abstract_inverted_index" in fields) == (ranking != "provider")
        assert embedder.calls == []
        works: list[dict[str, object]] = []
        for position in range(1, total_works + 1):
            work: dict[str, object] = {"id": f"W{position}", "title": f"Paper {position}"}
            if position in eligible_positions:
                if position % 3 == 0:
                    work["has_content"] = {"grobid_xml": True}
                elif position % 3 == 1:
                    work["has_content"] = {"pdf": True}
                else:
                    work["locations"] = [
                        {"is_oa": True, "pdf_url": f"https://oa.test/{position}.pdf"}
                    ]
            if position not in expected:
                work["abstract_inverted_index"] = "unused malformed ranking data"
            works.append(work)
        return httpx.Response(200, json={"results": works})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search(
                "q",
                limit=module.DEFAULT_ELIGIBLE_POOL_TARGET,
                embedder=None if ranking == "provider" else embedder,
            )
            ranked = (expected[-1], *expected[:-1]) if expected and ranking == "local" else expected
            assert tuple(candidate.source.key for candidate in candidates) == tuple(
                f"W{position}" for position in ranked
            )

    asyncio.run(scenario())
    assert requests == 1
    assert embedder.calls == ([("q", *texts)] if expected and ranking != "provider" else [])


@pytest.mark.parametrize("abstract", [{"bad": [-1]}, {"bad": ["position"]}, "malformed", []])
def test_provider_order_search_ignores_unrequested_malformed_abstracts(
    abstract: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_ranking(_: object) -> str:
        pytest.fail("provider-order retrieval must not construct ranking text")

    monkeypatch.setattr(module._Work, "ranking_text", unexpected_ranking)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["search"] == "q"
        assert "abstract_inverted_index" not in request.url.params["select"].split(",")
        return httpx.Response(
            200,
            json={
                "results": [
                    {"id": "W2", "has_content": {"pdf": True}, "abstract_inverted_index": abstract},
                    {"id": "W1", "has_content": {"grobid_xml": True}},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search("q", limit=2)
            assert tuple(candidate.source.key for candidate in candidates) == ("W2", "W1")
            assert all(candidate.ranking_text == "" for candidate in candidates)

    asyncio.run(scenario())


@pytest.mark.parametrize("ranking", ["local", "fallback", "provider"])
@pytest.mark.parametrize(
    "requested_limit,discovery_pool,eligible_positions",
    [(2, 12, (2, 4, 5)), (7, 12, tuple(range(1, 13))), (7, 12, (2, 5, 9, 12))],
    ids=["requested-target", "larger-target", "partial-pool"],
)
def test_requested_eligible_target_is_independent_of_discovery_pool(
    ranking: str,
    requested_limit: int,
    discovery_pool: int,
    eligible_positions: tuple[int, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "DISCOVERY_POOL_SIZE", discovery_pool)
    expected = eligible_positions[:requested_limit]
    texts = tuple(f"Paper {position}" for position in expected)
    embedder = FakeEmbedder(
        ()
        if ranking == "fallback"
        else ((1, 0), *((1, 0) if position == expected[-1] else (0, 1) for position in expected))
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert requests == 1
        assert request.url.host == "api.openalex.org" and request.url.path == "/works"
        assert request.url.params["search"] == "q"
        assert request.url.params["per_page"] == str(discovery_pool)
        assert "page" not in request.url.params and "cursor" not in request.url.params
        assert ("abstract_inverted_index" in request.url.params["select"].split(",")) == (
            ranking != "provider"
        )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": f"W{position}",
                        "title": f"Paper {position}",
                        "has_content": {"pdf": position in eligible_positions},
                    }
                    for position in range(1, discovery_pool + 1)
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            candidates = await OpenAlex(client=client).search(
                "q", limit=requested_limit, embedder=None if ranking == "provider" else embedder
            )
            ranked = (expected[-1], *expected[:-1]) if ranking == "local" else expected
            assert tuple(candidate.source.key for candidate in candidates) == tuple(
                f"W{position}" for position in ranked
            )

    asyncio.run(scenario())
    assert requests == 1
    assert embedder.calls == ([("q", *texts)] if ranking != "provider" else [])


@pytest.mark.parametrize(
    "abstract",
    [
        "malformed",
        [],
        {"bad": "positions"},
        {"bad": ["position"]},
        {"bad": [True]},
        {"bad": [-1]},
        {"one": [0], "two": [0]},
    ],
)
@pytest.mark.parametrize("eligible", [False, True])
def test_ranking_only_abstract_validation_happens_after_content_eligibility(
    abstract: object,
    eligible: bool,
) -> None:
    embedder = FakeEmbedder(((1, 0), (1, 0)))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org" and request.url.path == "/works"
        assert "abstract_inverted_index" in request.url.params["select"].split(",")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "W9",
                        "title": "Malformed ranking input",
                        "has_content": {"pdf": eligible},
                        "abstract_inverted_index": abstract,
                    },
                    {
                        "id": "W1",
                        "title": "Usable",
                        "has_content": {"grobid_xml": True},
                        "abstract_inverted_index": {"valid": [1], "A": [0]},
                    },
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(client=client)
            if eligible:
                with pytest.raises(OpenAlexError, match=r"^malformed_search_response$") as error:
                    await atlas.search("q", limit=2, embedder=embedder)
                assert error.value.__cause__ is None
            else:
                candidates = await atlas.search("q", limit=2, embedder=embedder)
                assert tuple(candidate.source.key for candidate in candidates) == ("W1",)

    asyncio.run(scenario())
    assert embedder.calls == ([] if eligible else [("q", "Usable\n\nA valid")])
