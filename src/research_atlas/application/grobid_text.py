"""Versioned, deterministic TEI projection onto exact UTF-8 evidence bytes."""

from dataclasses import replace
from hashlib import sha256
from typing import NoReturn
from uuid import uuid7
from xml.etree import ElementTree as ET
from xml.parsers.expat import ExpatError, ParserCreate

from research_atlas.domain.content import SourceDocument

PROJECTION_VERSION = "atlas.grobid-text.v1"
_NS = "{http://www.tei-c.org/ns/1.0}"
_MAX_BYTES = 32 * 1024 * 1024


def _reject_declaration(*_: object) -> NoReturn:
    raise ValueError("XML declarations of entities or document types are unsupported")


def prepare_grobid_text(parent: SourceDocument, content: bytes) -> tuple[SourceDocument, bytes]:
    if parent.status != "usable" or parent.content_kind != "grobid_xml":
        raise ValueError("projection requires a usable GROBID XML document")
    if sha256(content).hexdigest() != parent.content_sha256:
        raise ValueError("parent content checksum mismatch")
    if len(content) > _MAX_BYTES:
        raise ValueError("XML exceeds projection bound")
    try:
        # Expat rejects DTDs even with non-UTF-8 XML encodings, before building a tree.
        parser = ParserCreate()
        parser.StartDoctypeDeclHandler = _reject_declaration
        parser.EntityDeclHandler = _reject_declaration
        parser.ExternalEntityRefHandler = _reject_declaration
        parser.Parse(content, True)
        root = ET.fromstring(content)
    except (ExpatError, ET.ParseError, ValueError, LookupError) as error:
        raise ValueError("unsafe or malformed GROBID XML") from error
    if root.tag != _NS + "TEI":
        raise ValueError("expected namespaced GROBID TEI")

    def text(node: ET.Element) -> str:
        return " ".join("".join(node.itertext()).split())

    blocks: list[str] = []
    title = root.find(f"{_NS}teiHeader/{_NS}fileDesc/{_NS}titleStmt/{_NS}title")
    if title is not None and text(title):
        blocks.append(text(title))
    abstract = root.find(f"{_NS}teiHeader/{_NS}profileDesc/{_NS}abstract")
    body = root.find(f"{_NS}text/{_NS}body")

    def append_blocks(node: ET.Element) -> None:
        # Emit leaf prose blocks once, preserving inline text and document order.
        if node.tag in {_NS + tag for tag in ("head", "p", "item", "formula", "figDesc")}:
            if text(node):
                blocks.append(text(node))
        elif len(node):
            for child in node:
                append_blocks(child)
        elif text(node):
            blocks.append(text(node))

    if abstract is not None:
        append_blocks(abstract)
    if body is None or not text(body):
        raise ValueError("GROBID TEI has no usable research body")
    append_blocks(body)
    if not blocks:
        raise ValueError("GROBID TEI has no usable research text")
    prepared = ("\n\n".join(blocks) + "\n").encode("utf-8")
    return replace(
        parent,
        document_id=uuid7(),
        content_kind="grobid_text",
        retrieval_context=f"{PROJECTION_VERSION}; parent_source_document_id={parent.document_id}",
        media_type="text/plain; charset=utf-8",
        content_sha256=sha256(prepared).hexdigest(),
    ), prepared
