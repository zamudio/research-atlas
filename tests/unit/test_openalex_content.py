import asyncio
import gzip
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from research_atlas.application.ports.document_acquisition import DocumentAcquisitionResult
from research_atlas.infrastructure.providers import openalex_content
from research_atlas.infrastructure.providers.openalex_content import (
    MAX_XML_BYTES,
    OpenAlexDocumentAcquirer,
)

XML = b'<?xml version="1.0"?><TEI xmlns="http://www.tei-c.org/ns/1.0"><text>Exact.</text></TEI>'
KEY = "test-only-credential"
URL = "https://content.openalex.org/works/W123.grobid-xml"


class ControlledStream(httpx.AsyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self.chunks = chunks
        self.consumed = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def acquire(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str | None = KEY,
    delays: list[float] | None = None,
    work_id: str = "W123",
) -> DocumentAcquisitionResult:
    async def sleep(delay: float) -> None:
        if delays is not None:
            delays.append(delay)

    async def scenario() -> DocumentAcquisitionResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await OpenAlexDocumentAcquirer(api_key, client, retry_sleep=sleep).acquire(
                work_id
            )

    return asyncio.run(scenario())


@pytest.mark.parametrize("xml", [XML, b"<html><body><tei><text>Older</text></tei></body></html>"])
@pytest.mark.parametrize("compressed", [False, True])
def test_exact_xml_bearer_auth_and_transport_decoding(xml: bytes, compressed: bool) -> None:
    stream = ControlledStream((gzip.compress(xml) if compressed else xml,))

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL and KEY not in str(request.url)
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 20.0
        )
        return httpx.Response(
            200, stream=stream, headers={"Content-Encoding": "gzip"} if compressed else {}
        )

    result = acquire(handler, work_id="https://openalex.org/W123")
    assert result.status == "usable" and result.content == xml
    assert result.source_url == URL and result.media_type == "application/xml"
    assert result.content_kind == "grobid_xml" and result.retrieved_at.tzinfo is not None
    assert KEY not in result.retrieval_context and stream.closed


@pytest.mark.parametrize("api_key", [None, "", " \t"])
def test_missing_key_fails_without_network(api_key: str | None) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not request without an API key")

    result = acquire(handler, api_key=api_key)
    assert result.status == "failed" and result.content is None
    assert "missing_api_key" in result.retrieval_context


@pytest.mark.parametrize("work_id", ["", "A123", "W1?api_key=secret", "https://evil.test/W1"])
def test_invalid_identity_fails_before_network(work_id: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid identity must not reach network")

    with pytest.raises(ValueError, match="invalid OpenAlex acquisition identity"):
        acquire(handler, work_id=work_id)


@pytest.mark.parametrize(
    "code, expected",
    [(404, "unavailable"), (401, "failed"), (403, "failed"), (400, "failed"), (302, "failed")],
)
def test_absence_client_errors_and_redirects_are_safe(code: int, expected: str) -> None:
    stream = ControlledStream((f"remote secret {KEY}".encode(),))
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(code, stream=stream, headers={"Location": "https://evil.test/steal"})

    result = acquire(handler)
    assert result.status == expected and result.content is None and calls == 1
    assert KEY not in repr(result) and "remote secret" not in repr(result)
    assert stream.consumed == 0 and stream.closed


@pytest.mark.parametrize("code", [429, 500, 503])
@pytest.mark.parametrize("succeeds", [False, True])
def test_transient_retries_and_exhaustion(code: int, succeeds: bool) -> None:
    calls = 0
    delays: list[float] = []
    errors: list[ControlledStream] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if succeeds and calls == 3:
            return httpx.Response(200, content=XML)
        stream = ControlledStream((f"remote secret {KEY}".encode(),))
        errors.append(stream)
        return httpx.Response(code, stream=stream, headers={"Retry-After": "999999"})

    result = acquire(handler, delays=delays)
    assert calls == 3 and delays == [20.0, 20.0]
    assert result.status == ("usable" if succeeds else "failed")
    assert KEY not in repr(result) and "remote secret" not in repr(result)
    assert all(stream.closed and stream.consumed == 0 for stream in errors)


@pytest.mark.parametrize("succeeds", [False, True])
def test_transport_failures_are_retried_and_sanitized(succeeds: bool) -> None:
    calls = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if succeeds and calls == 3:
            return httpx.Response(200, content=XML)
        raise httpx.ReadError(f"remote secret {KEY}", request=request)

    result = acquire(handler, delays=delays)
    assert calls == 3 and delays == [0.5, 1.0]
    assert result.status == ("usable" if succeeds else "failed")
    assert KEY not in repr(result) and "remote secret" not in repr(result)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b" \n",
        b"<TEI>",
        b"remote secret",
        b"<x>\x00</x>",
        b'<?xml version="1.0" encoding="unknown"?><x/>',
    ],
)
def test_empty_or_malformed_success_is_not_usable(content: bytes) -> None:
    result = acquire(lambda _request: httpx.Response(200, content=content))
    assert result.status == "failed" and result.content is None
    assert "remote secret" not in repr(result)


@pytest.mark.parametrize("encoding", [None, "identity", " Identity "])
def test_declared_oversize_stops_without_reading_body(encoding: str | None) -> None:
    stream = ControlledStream((XML,))
    headers = {"Content-Length": str(MAX_XML_BYTES + 1)}
    if encoding is not None:
        headers["Content-Encoding"] = encoding
    result = acquire(lambda _request: httpx.Response(200, stream=stream, headers=headers))
    assert result.status == "incomplete" and result.content is None
    assert stream.consumed == 0 and stream.closed


def test_stream_crossing_bound_stops_and_discards_partial_content() -> None:
    stream = ControlledStream((b"x" * (1024 * 1024),) * 33 + (b"must not consume",))
    result = acquire(lambda _request: httpx.Response(200, stream=stream))
    assert result.status == "incomplete" and result.content is None
    assert stream.consumed == 33 and stream.closed


@pytest.mark.parametrize("compressed", [False, True])
def test_exact_size_bound_can_be_usable(compressed: bool) -> None:
    xml = b"<x>" + b"x" * (MAX_XML_BYTES - 7) + b"</x>"
    stream = ControlledStream((gzip.compress(xml) if compressed else xml,))
    result = acquire(
        lambda _request: httpx.Response(
            200, stream=stream, headers={"Content-Encoding": "gzip"} if compressed else {}
        )
    )
    assert result.status == "usable" and result.content == xml
    assert stream.closed


def test_gzip_transport_length_does_not_establish_decoded_size() -> None:
    stream = ControlledStream((gzip.compress(XML),))
    result = acquire(
        lambda _request: httpx.Response(
            200,
            stream=stream,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(MAX_XML_BYTES + 1),
            },
        )
    )
    assert result.status == "usable" and result.content == XML
    assert stream.consumed == 1 and stream.closed


def test_bad_transport_encoding_is_safe_failure() -> None:
    result = acquire(
        lambda _request: httpx.Response(
            200, stream=ControlledStream((b"remote secret",)), headers={"Content-Encoding": "gzip"}
        )
    )
    assert result.status == "failed" and result.content is None
    assert "remote secret" not in repr(result)


def test_stream_failure_retries_whole_document_without_partial_bytes() -> None:
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"<wrong>"
            raise httpx.ReadError(f"remote secret {KEY}")

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(200, stream=BrokenStream())
            if calls == 1
            else httpx.Response(200, content=XML)
        )

    result = acquire(handler)
    assert calls == 2 and result.content == XML and result.status == "usable"


def test_compressed_content_is_bounded_after_transport_decoding() -> None:
    stream = ControlledStream((gzip.compress(b"x" * (MAX_XML_BYTES + 1)), b"never consume"))
    result = acquire(
        lambda _request: httpx.Response(
            200,
            stream=stream,
            headers={"Content-Encoding": "gzip", "Content-Length": "1234"},
        )
    )
    assert result.status == "incomplete" and result.content is None
    assert stream.consumed == 1 and stream.closed


def test_attempt_deadline_bounds_a_slow_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openalex_content, "_TIMEOUT_SECONDS", 0.01)
    calls = 0
    closed = 0

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            await asyncio.sleep(10)
            yield XML

        async def aclose(self) -> None:
            nonlocal closed
            closed += 1

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=SlowStream())

    result = acquire(handler)
    assert calls == closed == 3 and result.status == "failed" and result.content is None
