import asyncio
from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

import research_atlas.content as module
from research_atlas.content import UnusableContent, prepare_content
from research_atlas.extraction import extract_evidence
from tests.test_embeddings import FakeEmbedder
from tests.test_extraction import OTHER, PASSAGE, SOURCE, FakeModel, proposal_bytes


def text_pdf(text: str = PASSAGE, *, pages: int = 1, encrypted: bool = False) -> bytes:
    """Deterministic local PDF, with an actual font and text content stream."""
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        font_reference = writer._add_object(font)  # pyright: ignore[reportPrivateUsage]
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_reference})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)  # pyright: ignore[reportPrivateUsage]
    if encrypted:
        writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_preparation_recovers_incorrect_cross_reference_offset() -> None:
    original = text_pdf().rsplit(b"startxref\n", 1)[0] + b"startxref\n1\n%%EOF\n"
    with pytest.raises(PdfReadError):
        PdfReader(BytesIO(original), strict=True)

    acquired = prepare_content(original, "pdf")
    assert acquired.original == original
    assert acquired.index.resolve("p0001") == PASSAGE


def test_pdf_preparation_is_stable_and_grounding_uses_exact_text_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = text_pdf(PASSAGE + "\n" + OTHER)
    acquired = prepare_content(original, "pdf")
    assert acquired.kind == "pdf" and acquired.original == original
    assert acquired.index == prepare_content(original, "pdf").index
    assert acquired.index.resolve("p0001") == PASSAGE + "\n" + OTHER

    def fail(*_: object) -> bytes:
        pytest.fail("prepared document must not be projected twice")

    monkeypatch.setattr(module, "_project_pdf", fail)

    class Model(FakeModel):
        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert input_text == acquired.index.model_text
            return proposal_bytes()

    result = asyncio.run(
        extract_evidence(question="learning?", source=SOURCE, content=acquired, model=Model(b""))
    )
    assert result.content_sha256 == sha256(original).hexdigest()
    assert result.evidence[0].passages == (acquired.index.resolve("p0001"),)


@pytest.mark.parametrize(
    "original",
    [
        b"<html>not PDF</html>",
        b"%PDF-1.4\ninvalid\n%%EOF",
        text_pdf(""),
        text_pdf("123 456"),
        text_pdf("tiny text"),
        text_pdf(encrypted=True),
    ],
)
def test_invalid_or_unusable_pdf_is_a_safe_miss(original: bytes) -> None:
    with pytest.raises(UnusableContent):
        prepare_content(original, "pdf")


@pytest.mark.parametrize(
    "bound",
    [
        "MAX_DOCUMENT_BYTES",
        "MAX_PDF_PAGES",
        "MAX_PDF_STREAM_BYTES",
        "MAX_PDF_TEXT_CHARACTERS",
    ],
)
def test_pdf_preparation_bounds(bound: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, bound, 1)
    with pytest.raises(UnusableContent):
        prepare_content(text_pdf(pages=2), "pdf")


def test_unexpected_parser_errors_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object, **__: object) -> object:
        raise RuntimeError("programming failure")

    monkeypatch.setattr(module, "PdfReader", broken)
    with pytest.raises(RuntimeError, match="programming failure"):
        prepare_content(text_pdf(), "pdf")


def test_pdf_model_invisible_passage_is_rejected() -> None:
    acquired = prepare_content(text_pdf(pages=2), "pdf")
    assert tuple(acquired.index.passages) == ("p0001", "p0002")

    class Model(FakeModel):
        async def fits_context(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bool:
            return len(input_text) <= len(f"[p0001] {PASSAGE}\n")

        async def generate(
            self, instructions: str, input_text: str, schema: Mapping[str, object]
        ) -> bytes:
            assert "[p0001]" in input_text and "[p0002]" not in input_text
            return proposal_bytes(("p0002",))

    with pytest.raises(ValueError, match="model-invisible"):
        asyncio.run(
            extract_evidence(
                question="learning?",
                source=SOURCE,
                content=acquired,
                model=Model(b""),
                embedder=FakeEmbedder(((1, 0), (1, 0), (0, 1))),
            )
        )
