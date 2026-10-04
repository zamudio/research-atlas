"""In-memory acquisition boundary: original bytes and one prepared passage index."""

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, ParseError, PdfReadError

from research_atlas.grobid import project_grobid
from research_atlas.passages import PassageIndex, build_passage_index

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
MAX_PDF_TEXT_CHARACTERS = 4 * 1024 * 1024
ContentKind = Literal["grobid", "pdf"]


class UnusableContent(ValueError):
    """Expected document/preparation miss; carries only a safe local code."""


@dataclass(frozen=True, slots=True)
class AcquiredContent:
    original: bytes
    kind: ContentKind
    index: PassageIndex


def prepare_content(original: bytes, kind: ContentKind) -> AcquiredContent:
    if len(original) > MAX_DOCUMENT_BYTES:
        raise UnusableContent("content_size_exceeded")
    if kind == "grobid":
        try:
            prepared = project_grobid(original)
        except ValueError:
            raise UnusableContent("unusable_grobid") from None
    elif kind == "pdf":
        prepared = _project_pdf(original)
    else:
        raise ValueError("unknown acquired content kind")
    try:
        index = build_passage_index(prepared)
    except ValueError:
        raise UnusableContent("unusable_passages") from None
    return AcquiredContent(original, kind, index)


def _project_pdf(original: bytes) -> bytes:
    # Do not hand HTML/error pages to the parser, even if labeled application/pdf.
    if not original.startswith(b"%PDF-") or b"%%EOF" not in original[-1024:]:
        raise UnusableContent("invalid_pdf")
    blocks: list[str] = []
    characters = 0
    stream_bytes = 0
    try:
        reader = PdfReader(BytesIO(original), strict=False)
        if reader.is_encrypted:
            raise UnusableContent("encrypted_pdf")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise UnusableContent("pdf_page_bound")
        for page in reader.pages:
            contents = page.get_contents()
            size = len(contents.get_data()) if contents is not None else 0
            stream_bytes += size
            if size > MAX_PDF_STREAM_BYTES or stream_bytes > MAX_DOCUMENT_BYTES:
                raise UnusableContent("pdf_stream_bound")
            text = page.extract_text()
            characters += len(text)
            if characters > MAX_PDF_TEXT_CHARACTERS:
                raise UnusableContent("pdf_text_bound")
            # Preserve parser text, including line breaks and whitespace. Page boundaries
            # become block boundaries; no semantic rewriting or speculative dehyphenation.
            blocks.extend(block for block in text.removesuffix("\n").split("\n\n") if block.strip())
    except PdfReadError, ParseError, LimitReachedError:
        raise UnusableContent("invalid_pdf") from None
    # Reject blank scans, page-number-only output and tiny scraps of text.
    if sum(character.isalpha() for block in blocks for character in block) < 40:
        raise UnusableContent("no_meaningful_pdf_text")
    return ("\n\n".join(blocks) + "\n").encode("utf-8")
