"""GROBID and PDF converge on ordered passages; only whitespace is normalized."""

import re
from io import BytesIO
from typing import NoReturn
from xml.etree import ElementTree as ET
from xml.parsers.expat import ExpatError, ParserCreate

from pypdf import PdfReader
from pypdf.errors import LimitReachedError, ParseError, PdfReadError

from research_atlas.models import ContentSource, Document, Passage, Work

MAX_DOCUMENT_BYTES = 32 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_PDF_STREAM_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARACTERS = 4 * 1024 * 1024
_PASSAGE_LENGTH = 2000


def _reject_declaration(*_: object) -> NoReturn:
    raise ValueError("XML entities and document types are unsupported")


def _xml_blocks(content: bytes) -> list[tuple[str | None, str]]:
    try:
        parser = ParserCreate()
        parser.StartDoctypeDeclHandler = _reject_declaration
        parser.EntityDeclHandler = _reject_declaration
        parser.ExternalEntityRefHandler = _reject_declaration
        parser.Parse(content, True)
        root = ET.fromstring(content)
    except (ExpatError, ET.ParseError, ValueError, LookupError) as error:
        raise ValueError("unsafe or malformed GROBID XML") from error

    def local_name(node: ET.Element) -> str:
        return node.tag.rsplit("}", 1)[-1].casefold()

    tei = root
    if local_name(root) == "html":
        wrapper = next((node for node in root if local_name(node) == "body"), None)
        tei = (
            next((node for node in wrapper if local_name(node) == "tei"), None)
            if wrapper is not None
            else None
        )
    if tei is None or local_name(tei) != "tei":
        raise ValueError("expected GROBID TEI")
    text_node = next((node for node in tei if local_name(node) == "text"), None)
    if text_node is None:
        raise ValueError("GROBID XML has no research body")
    body = next((node for node in text_node if local_name(node) == "body"), None)
    # Older OpenAlex files have html/body/tei/text/div, without a TEI body.
    roots = (
        [body] if body is not None else [node for node in text_node if local_name(node) == "div"]
    )

    def text(node: ET.Element) -> str:
        return " ".join("".join(node.itertext()).split())

    blocks: list[tuple[str | None, str]] = []
    # Iterative traversal handles nested sections without recursive parser limits.
    pending: list[tuple[ET.Element, str | None]] = [(node, None) for node in reversed(roots)]
    while pending:
        node, section = pending.pop()
        name = local_name(node)
        if name in {"head", "teiheader", "front", "abstract", "back", "listbibl"}:
            continue
        if name == "div":
            heading = next((child for child in node if local_name(child) == "head"), None)
            if heading is not None:
                section = text(heading) or section
        if name in {"p", "item", "formula", "figdesc"}:
            if value := text(node):
                blocks.append((section, value))
        else:
            pending.extend((child, section) for child in reversed(node))
    return blocks


def _pdf_blocks(content: bytes) -> list[tuple[str | None, str]]:
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:
        raise ValueError("invalid PDF")
    blocks: list[tuple[str | None, str]] = []
    stream_bytes = characters = 0
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise ValueError("encrypted or oversized PDF")
        for page in reader.pages:
            contents = page.get_contents()
            size = len(contents.get_data()) if contents is not None else 0
            stream_bytes += size
            if size > MAX_PDF_STREAM_BYTES or stream_bytes > MAX_DOCUMENT_BYTES:
                raise ValueError("PDF stream exceeds preparation bounds")
            text = page.extract_text()
            characters += len(text)
            if characters > MAX_TEXT_CHARACTERS:
                raise ValueError("PDF text exceeds preparation bounds")
            blocks.extend((None, block) for block in re.split(r"\n\s*\n", text) if block.strip())
    except (
        PdfReadError,
        ParseError,
        LimitReachedError,
        ValueError,
        TypeError,
        IndexError,
        KeyError,
    ) as error:
        raise ValueError("unreadable PDF") from error
    return blocks


def prepare(work: Work, source: ContentSource, content: bytes) -> Document:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("content exceeds preparation bounds")
    blocks = _xml_blocks(content) if source.kind == "grobid_xml" else _pdf_blocks(content)
    if sum(len(text) for _, text in blocks) > MAX_TEXT_CHARACTERS:
        raise ValueError("text exceeds preparation bounds")
    if sum(character.isalpha() for _, text in blocks for character in text) < 40:
        raise ValueError("no usable full text")
    passages: list[Passage] = []
    for section, text in blocks:
        text = " ".join(text.split())
        # Split long blocks only at whitespace. Every passage is a source substring.
        while text:
            end = len(text)
            if end > _PASSAGE_LENGTH:
                end = text.rfind(" ", 0, _PASSAGE_LENGTH + 1)
                if end <= 0:
                    end = text.find(" ", _PASSAGE_LENGTH)
                    if end < 0:
                        end = len(text)
            passages.append(
                Passage(passage_id=f"p{len(passages) + 1:04d}", section=section, text=text[:end])
            )
            text = text[end:].lstrip()
    return Document(work=work, source=source, passages=tuple(passages))
