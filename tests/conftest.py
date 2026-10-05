"""Deterministic full-text fixtures; unexpected HTTP requests fail every normal test."""

from collections.abc import Callable
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from research_atlas.config import Settings
from research_atlas.models import Work

type MockHTTP = Callable[[Callable[[httpx.Request], httpx.Response]], None]
type MakePDF = Callable[[tuple[str, ...]], bytes]

RESULTS = "Participants reported lower stress after spending time outside in a park."
METHODS = "Participants were assigned to outdoor walking or an indoor comparison condition."


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_ATLAS_OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_ATLAS_HTTP_TIMEOUT_SECONDS", raising=False)

    async def reject(
        _transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        pytest.fail(
            f"Unexpected HTTP request: {request.method} {request.url.host}{request.url.path}"
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject)


@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch) -> MockHTTP:
    def install(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        async def send(
            _transport: httpx.AsyncHTTPTransport, request: httpx.Request
        ) -> httpx.Response:
            return handler(request)

        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)

    return install


@pytest.fixture
def settings() -> Settings:
    return Settings.model_validate({"openalex_api_key": "test-secret"})


@pytest.fixture
def work() -> Work:
    return Work(
        openalex_id="W1",
        title="Outdoor exposure study",
        doi="https://doi.org/10.1234/example",
        year=2024,
    )


@pytest.fixture
def grobid() -> bytes:
    return f"""<TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader><profileDesc><abstract>
        <p>Abstract-only wording must never substitute for full text.</p>
      </abstract></profileDesc></teiHeader>
      <text><body>
        <div><head>Methods</head><p>{METHODS}</p></div>
        <div><head>Results</head><p>{RESULTS}</p></div>
      </body><back><p>Bibliography-only wording.</p></back></text>
    </TEI>""".encode()


@pytest.fixture
def make_pdf() -> MakePDF:
    def build(texts: tuple[str, ...]) -> bytes:
        writer = PdfWriter()
        for text in texts:
            page = writer.add_blank_page(width=612, height=792)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            reference = writer._add_object(font)  # pyright: ignore[reportPrivateUsage]
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): reference})}
            )
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)  # pyright: ignore[reportPrivateUsage]
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    return build


@pytest.fixture
def pdf(make_pdf: MakePDF) -> bytes:
    return make_pdf((METHODS, RESULTS))
