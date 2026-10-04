import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

import research_atlas.openalex as module
from research_atlas.models import Source
from research_atlas.openalex import OpenAlex, OpenAlexError
from tests.test_content import text_pdf
from tests.test_extraction import SOURCE, XML
from tests.test_openalex import KEY, no_sleep

PDF = text_pdf()


@pytest.mark.parametrize("route", ["grobid", "cached", "oa", "second_oa", "none"])
def test_route_preference_and_next_oa_location(route: str) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "content.openalex.org":
            assert request.headers["Authorization"] == "Bearer private-key"
            if request.url.path.endswith("grobid-xml") and route == "grobid":
                return httpx.Response(200, content=XML)
            if request.url.path.endswith(".pdf") and route == "cached":
                return httpx.Response(200, content=PDF)
            return httpx.Response(404)
        if request.url.host == "api.openalex.org":
            assert request.url.path == f"/works/{SOURCE.key}"
            assert request.url.params["select"] == "id,best_oa_location,primary_location,locations"
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": False, "pdf": False},
                    "best_oa_location": {"is_oa": True, "pdf_url": "https://oa.test/first"},
                    "locations": [
                        {"is_oa": False, "pdf_url": "https://closed.test/paper.pdf"},
                        {"is_oa": True, "pdf_url": "https://oa.test/first"},
                        {"is_oa": True, "pdf_url": "https://oa.test/second"},
                    ],
                },
            )
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        assert request.url.host == "oa.test"
        if route == "oa" or (route == "second_oa" and request.url.path == "/second"):
            return httpx.Response(200, content=PDF)
        return httpx.Response(403, text="remote secret body")

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "inherited-secret", "Cookie": "secret"},
            auth=("username", "password"),
        ) as client:
            result = await OpenAlex(KEY, client).fetch_content(SOURCE)
            if route == "none":
                assert result is None
            else:
                assert result is not None
                assert result.original == (XML if route == "grobid" else PDF)
                assert result.kind == ("grobid" if route == "grobid" else "pdf")

    asyncio.run(scenario())
    metadata = f"https://api.openalex.org/works/{SOURCE.key}?select=id%2Cbest_oa_location%2Cprimary_location%2Clocations"
    expected = [f"https://content.openalex.org/works/{SOURCE.key}.grobid-xml"]
    if route != "grobid":
        expected.append(metadata)
        expected.append("https://oa.test/first")
        if route in {"second_oa", "none", "cached"}:
            expected.append("https://oa.test/second")
        if route in {"cached", "none"}:
            expected.append(f"https://content.openalex.org/works/{SOURCE.key}.pdf")
    assert calls == expected


@pytest.mark.parametrize("cached_xml", [b"<TEI", b"", b"oversized", None])
@pytest.mark.parametrize("cached_pdf_advertised", [False, True])
def test_unusable_grobid_tries_oa_before_cached_pdf_without_best_pdf(
    cached_xml: bytes | None,
    cached_pdf_advertised: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "MAX_CONTENT_BYTES", len(PDF))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("grobid-xml"):
            if cached_xml == b"oversized":
                return httpx.Response(200, content=b"x" * (len(PDF) + 1))
            return (
                httpx.Response(404)
                if cached_xml is None
                else httpx.Response(200, content=cached_xml)
            )
        if request.url.host == "content.openalex.org":
            pytest.fail("usable OA PDF must prevent cached PDF request")
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": True, "pdf": cached_pdf_advertised},
                    "best_oa_location": {
                        "is_oa": True,
                        "landing_page_url": "https://oa.test/landing",
                    },
                    "locations": [{"is_oa": True, "pdf_url": "https://oa.test/direct"}],
                },
            )
        assert request.url.path == "/direct"
        return httpx.Response(200, content=PDF)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenAlex(KEY, client).fetch_content(SOURCE)
            assert result is not None and result.original == PDF

    asyncio.run(scenario())
    assert calls == [
        f"/works/{SOURCE.key}.grobid-xml",
        f"/works/{SOURCE.key}",
        "/direct",
    ]


@pytest.mark.parametrize("oa_pdf", [None, b"HTML", b"%PDF-1.4\nbroken\n%%EOF", text_pdf("")])
@pytest.mark.parametrize("cached_pdf", [PDF, None, b"HTML"])
def test_failed_or_unusable_oa_pdfs_fall_back_to_cached_pdf(
    oa_pdf: bytes | None,
    cached_pdf: bytes | None,
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("grobid-xml"):
            return httpx.Response(404)
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": False, "pdf": False},
                    "best_oa_location": {"is_oa": True, "pdf_url": "https://oa.test/first"},
                    "locations": [{"is_oa": True, "pdf_url": "https://oa.test/second"}],
                },
            )
        if request.url.host == "oa.test":
            return httpx.Response(404) if oa_pdf is None else httpx.Response(200, content=oa_pdf)
        assert request.url.path == f"/works/{SOURCE.key}.pdf"
        return (
            httpx.Response(404) if cached_pdf is None else httpx.Response(200, content=cached_pdf)
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            acquired = await OpenAlex(KEY, client).fetch_content(SOURCE)
            if cached_pdf == PDF:
                assert acquired is not None and acquired.kind == "pdf" and acquired.original == PDF
            else:
                assert acquired is None

    asyncio.run(scenario())
    assert paths == [
        f"/works/{SOURCE.key}.grobid-xml",
        f"/works/{SOURCE.key}",
        "/first",
        "/second",
        f"/works/{SOURCE.key}.pdf",
    ]


@pytest.mark.parametrize(
    "fault",
    [
        "transport",
        "html",
        "size",
        "redirect_loop",
        "private_redirect",
        "invalid_redirect",
        "invalid_port",
    ],
)
def test_external_failure_tries_next_pdf(fault: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MAX_CONTENT_BYTES", len(PDF))

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * len(PDF)
            yield b"x"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "content.openalex.org":
            assert request.url.path.endswith("grobid-xml")
            return httpx.Response(404)
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": False, "pdf": False},
                    "locations": [
                        {"is_oa": True, "pdf_url": "https://oa.test/first"},
                        {"is_oa": True, "pdf_url": "https://oa.test/second"},
                    ],
                },
            )
        assert request.url.host == "oa.test"
        if request.url.path == "/second":
            return httpx.Response(200, content=PDF)
        if fault == "transport":
            raise httpx.ReadTimeout("secret", request=request)
        if fault == "size":
            return httpx.Response(200, stream=Chunks())
        if fault == "invalid_redirect":
            return httpx.Response(302, headers={"Location": "http://["})
        if fault == "invalid_port":
            return httpx.Response(302, headers={"Location": "https://oa.test:invalid/pdf"})
        if fault in {"redirect_loop", "private_redirect"}:
            return httpx.Response(
                302,
                headers={
                    "Location": "/first" if fault == "redirect_loop" else "http://127.0.0.1/secret"
                },
            )
        return httpx.Response(
            200, content=b"<html>login</html>", headers={"Content-Type": "application/pdf"}
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenAlex(KEY, client).fetch_content(SOURCE)
            assert result is not None and result.original == PDF

    asyncio.run(scenario())


def test_external_redirect_can_resolve_pdf_without_credentials() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        paths.append(request.url.path)
        if request.url.path == "/direct":
            return httpx.Response(302, headers={"Location": "https://cdn.test/paper.pdf"})
        return httpx.Response(200, content=PDF)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            atlas = OpenAlex(KEY, client)
            result = await atlas._external_pdf("https://oa.test/direct")  # pyright: ignore[reportPrivateUsage]
            assert result == PDF

    asyncio.run(scenario())
    assert paths == ["/direct", "/paper.pdf"]


@pytest.mark.parametrize("code", [401, 403, 429])
@pytest.mark.parametrize("phase", ["metadata", "cached_grobid", "cached_pdf"])
def test_auth_and_budget_failures_surface(code: int, phase: str) -> None:
    failing_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("grobid-xml") and phase != "cached_grobid":
            return httpx.Response(404)
        if request.url.host == "api.openalex.org" and phase != "metadata":
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": False, "pdf": False},
                },
            )
        failing_urls.append(str(request.url))
        return httpx.Response(code, text="secret")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OpenAlexError, match=f"^http_{code}$"):
                await OpenAlex(KEY, client, retry_sleep=no_sleep).fetch_content(SOURCE)

    asyncio.run(scenario())
    assert len(failing_urls) == (3 if code == 429 else 1)
    target = {
        "metadata": f"https://api.openalex.org/works/{SOURCE.key}?",
        "cached_grobid": f"https://content.openalex.org/works/{SOURCE.key}.grobid-xml",
        "cached_pdf": f"https://content.openalex.org/works/{SOURCE.key}.pdf",
    }[phase]
    assert all(url.startswith(target) for url in failing_urls)


@pytest.mark.parametrize(
    "metadata",
    [b"not json secret", b'{"id":"W456"}', b'{"id":"W123","locations":"invalid"}'],
)
def test_malformed_or_wrong_work_metadata_surfaces_safely(metadata: bytes) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("grobid-xml"):
            return httpx.Response(404)
        assert request.url.host == "api.openalex.org"
        return httpx.Response(200, content=metadata)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OpenAlexError, match=r"^malformed_work_response$"):
                await OpenAlex(KEY, client).fetch_content(SOURCE)

    asyncio.run(scenario())


@pytest.mark.parametrize("grobid", [None, b"<TEI"])
@pytest.mark.parametrize("unusable_oa_pdf", [False, True])
def test_stale_negative_cached_pdf_metadata_does_not_suppress_probe(
    grobid: bytes | None,
    unusable_oa_pdf: bool,
) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200,
                json={
                    "id": SOURCE.key,
                    "has_content": {"grobid_xml": False, "pdf": False},
                    "locations": [{"is_oa": True, "pdf_url": "https://oa.test/unusable"}]
                    if unusable_oa_pdf
                    else [],
                },
            )
        if request.url.path.endswith("grobid-xml"):
            return httpx.Response(404) if grobid is None else httpx.Response(200, content=grobid)
        if request.url.host == "oa.test":
            return httpx.Response(200, content=text_pdf(""))
        return httpx.Response(200, content=PDF)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            acquired = await OpenAlex(KEY, client).fetch_content(SOURCE)
            assert acquired is not None and acquired.kind == "pdf" and acquired.original == PDF

    asyncio.run(scenario())
    assert paths == [
        f"/works/{SOURCE.key}.grobid-xml",
        f"/works/{SOURCE.key}",
        *(["/unusable"] if unusable_oa_pdf else []),
        f"/works/{SOURCE.key}.pdf",
    ]


@pytest.mark.parametrize("cached_pdf", [None, PDF])
def test_missing_work_metadata_still_allows_cached_pdf_probe(cached_pdf: bytes | None) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith(".pdf") and cached_pdf is not None:
            return httpx.Response(200, content=cached_pdf)
        return httpx.Response(404)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            acquired = await OpenAlex(KEY, client).fetch_content(SOURCE)
            if cached_pdf is None:
                assert acquired is None
            else:
                assert acquired is not None and acquired.original == cached_pdf

    asyncio.run(scenario())
    assert paths == [
        f"/works/{SOURCE.key}.grobid-xml",
        f"/works/{SOURCE.key}",
        f"/works/{SOURCE.key}.pdf",
    ]


def test_stale_negative_grobid_metadata_does_not_block_direct_probe() -> None:
    source = Source(
        "Let's not forget: Learning analytics are about learning", (), None, "W1982464953"
    )
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if request.url.host == "api.openalex.org":
            return httpx.Response(
                200, json={"id": source.key, "has_content": {"pdf": False, "grobid_xml": False}}
            )
        assert str(request.url) == "https://content.openalex.org/works/W1982464953.grobid-xml"
        return httpx.Response(200, content=XML)

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            acquired = await OpenAlex(KEY, client).fetch_content(source)
            assert acquired is not None and acquired.kind == "grobid" and acquired.original == XML

    asyncio.run(scenario())
    assert urls == ["https://content.openalex.org/works/W1982464953.grobid-xml"]


def test_unexpected_acquisition_failure_surfaces() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise RuntimeError("internal failure")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RuntimeError, match="internal failure"):
                await OpenAlex(KEY, client).fetch_content(SOURCE)

    asyncio.run(scenario())
