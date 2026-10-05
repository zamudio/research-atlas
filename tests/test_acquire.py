import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from conftest import MockHTTP
from research_atlas.acquire import acquire
from research_atlas.config import Settings
from research_atlas.models import ContentSource, Document, Failure, Work


@pytest.mark.parametrize("winner", [0, 1, 2, 3, None])
def test_deterministic_fallback_uses_only_preparable_content(
    winner: int | None,
    work: Work,
    grobid: bytes,
    pdf: bytes,
    mock_http: MockHTTP,
    settings: Settings,
) -> None:
    work.routes = (
        ContentSource(kind="grobid_xml", url="https://content.openalex.org/works/W1.grobid-xml"),
        ContentSource(kind="oa_pdf", url="https://oa.test/first"),
        ContentSource(kind="oa_pdf", url="https://oa.test/second"),
        ContentSource(kind="openalex_pdf", url="https://content.openalex.org/works/W1.pdf"),
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        index = len(calls)
        calls.append(str(request.url))
        if request.url.host == "content.openalex.org":
            assert request.headers["Authorization"] == "Bearer test-secret"
        else:
            assert "Authorization" not in request.headers and "Cookie" not in request.headers
        if index == winner:
            return httpx.Response(200, content=grobid if index == 0 else pdf)
        return httpx.Response(200, content=b"<html>Not full text</html>")

    mock_http(handler)

    async def run() -> None:
        async with httpx.AsyncClient(
            headers={"Authorization": "default-secret", "Cookie": "default-cookie"},
            auth=("user", "password"),
        ) as client:
            result = await acquire(work, client, settings)
        if winner is None:
            assert isinstance(result, Failure) and result.stage == "preparation"
        else:
            assert isinstance(result, Document)
            assert result.source == work.routes[winner] and result.work == work
        assert calls == [route.url for route in work.routes[: 4 if winner is None else winner + 1]]

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode", ["404", "403", "429", "500", "timeout", "oversized", "redirect_loop"]
)
def test_unavailable_content_records_a_paper_failure(
    mode: str, work: Work, mock_http: MockHTTP, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    work.routes = (ContentSource(kind="oa_pdf", url="https://oa.test/paper"),)
    monkeypatch.setattr("research_atlas.acquire.MAX_DOCUMENT_BYTES", 10)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if mode == "timeout":
            raise httpx.ReadTimeout("private remote details", request=request)
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 11)
        if mode == "redirect_loop":
            return httpx.Response(302, headers={"location": "/paper"})
        return httpx.Response(int(mode), text="private remote details")

    mock_http(handler)

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            result = await acquire(work, client, settings)
        assert isinstance(result, Failure)
        assert result.stage == "acquisition" and result.openalex_id == "W1"
        assert "private" not in result.reason

    asyncio.run(run())
    assert len(calls) == (4 if mode == "redirect_loop" else 1)


def test_redirect_provenance_and_credentials(
    work: Work, pdf: bytes, settings: Settings, mock_http: MockHTTP
) -> None:
    work.routes = (
        ContentSource(kind="openalex_pdf", url="https://content.openalex.org/works/W1.pdf"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "content.openalex.org":
            assert request.headers["Authorization"] == "Bearer test-secret"
            return httpx.Response(302, headers={"location": "https://cdn.test/paper.pdf"})
        assert request.url.host == "cdn.test"
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        return httpx.Response(200, content=pdf)

    mock_http(handler)

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            result = await acquire(work, client, settings)
        assert isinstance(result, Document)
        assert result.source.url == "https://cdn.test/paper.pdf"
        assert result.source.kind == "openalex_pdf"

    asyncio.run(run())


def test_private_redirect_is_rejected(work: Work, settings: Settings, mock_http: MockHTTP) -> None:
    work.routes = (ContentSource(kind="oa_pdf", url="https://oa.test/paper"),)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    mock_http(handler)

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            assert isinstance(await acquire(work, client, settings), Failure)

    asyncio.run(run())
    assert calls == ["https://oa.test/paper"]


def test_stream_size_bound_closes_response(
    work: Work, settings: Settings, mock_http: MockHTTP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("research_atlas.acquire.MAX_DOCUMENT_BYTES", 8)
    work.routes = (ContentSource(kind="oa_pdf", url="https://oa.test/paper"),)

    class Stream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"12345"
            yield b"67890"
            pytest.fail("Read beyond byte bound")

        async def aclose(self) -> None:
            self.closed = True

    stream = Stream()
    mock_http(lambda _: httpx.Response(200, stream=stream))

    async def run() -> None:
        async with httpx.AsyncClient() as client:
            assert isinstance(await acquire(work, client, settings), Failure)
        assert stream.closed

    asyncio.run(run())
