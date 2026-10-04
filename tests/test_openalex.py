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
from research_atlas.openalex import OpenAlex, OpenAlexError
from tests.test_extraction import SOURCE, XML

KEY = SecretStr("private-key")


async def no_sleep(_: float) -> None:
    pass


def work_response(
    request: httpx.Request, *, grobid: bool = True, pdf: bool = True
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": request.url.path.rsplit("/", 1)[1],
            "has_content": {"grobid_xml": grobid, "pdf": pdf},
        },
    )


def test_search_maps_ordered_citations_and_normalized_scholarly_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.params["search"] == "learning"
        assert request.url.params["per_page"] == "2"
        assert request.headers["Authorization"] == "Bearer private-key"
        assert "private-key" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
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
                    {"id": "W456"},
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(KEY, client)
            sources = await atlas.search("learning", limit=2)
            assert sources[0].key == "W123"
            assert sources[0].doi == "10.1234/abc"
            assert sources[0].openalex_id == "W123"
            assert sources[0].authors == ("First", "Second")
            assert sources[0].url == "https://example.org/paper"
            assert sources[1].key == "W456"
            assert "private-key" not in repr(atlas)
            assert set(asdict(sources[0])) == {
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
        return httpx.Response(200, json={"results": [{"id": "W2"}, {"id": "W1"}]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources = await OpenAlex(client=client).search("learning", semantic=True)
            assert [source.key for source in sources] == ["W2", "W1"]

    asyncio.run(scenario())
    assert waits == 1


@pytest.mark.parametrize(
    "query,limit,semantic",
    [
        (" ", 1, False),
        ("x" * 2001, 1, False),
        ("q", 0, False),
        ("q", 201, False),
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
        b'{"results":[{"id":"W1"},{"id":"W2"}]}',
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
            return work_response(request)
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
            result = await OpenAlex(KEY, client).fetch_content(SOURCE)
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
        asyncio.run(OpenAlex().fetch_content(SOURCE))
