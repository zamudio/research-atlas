from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter

from conftest import METHODS, RESULTS, MakePDF
from research_atlas.models import ContentSource, Work
from research_atlas.prepare import prepare

XML_SOURCE = ContentSource(
    kind="grobid_xml", url="https://content.openalex.org/works/W1.grobid-xml"
)
PDF_SOURCE = ContentSource(kind="oa_pdf", url="https://oa.test/paper.pdf")


def test_grobid_body_sections_and_stable_passages(work: Work, grobid: bytes) -> None:
    document = prepare(work, XML_SOURCE, grobid)
    assert document == prepare(work, XML_SOURCE, grobid)
    assert document.work == work and document.source == XML_SOURCE
    assert [(p.passage_id, p.section, p.text) for p in document.passages] == [
        ("p0001", "Methods", METHODS),
        ("p0002", "Results", RESULTS),
    ]


@pytest.fixture(params=["", ' xmlns="http://www.w3.org/1999/xhtml"'])
def legacy_grobid(request: pytest.FixtureRequest) -> bytes:
    return f"""<html{request.param}><body><tei>
      <teiheader><abstract><p>Header abstract must not become evidence.</p></abstract></teiheader>
      <text>
        <front><p>Front matter must not become evidence.</p></front>
        <abstract><p>Abstract-only text must not become evidence.</p></abstract>
        <div><head>Methods</head><p>{METHODS}</p></div>
        <DiV><HeAd>Results</HeAd><P>{RESULTS}</P></DiV>
        <back><div><p>Bibliography-only text must not become evidence.</p></div></back>
      </text>
    </tei></body></html>""".encode()


def test_legacy_grobid_preserves_sections_order_and_ids(
    work: Work, grobid: bytes, legacy_grobid: bytes
) -> None:
    document = prepare(work, XML_SOURCE, legacy_grobid)
    assert document == prepare(work, XML_SOURCE, legacy_grobid)
    assert document == prepare(work, XML_SOURCE, grobid)
    assert [(p.passage_id, p.section, p.text) for p in document.passages] == [
        ("p0001", "Methods", METHODS),
        ("p0002", "Results", RESULTS),
    ]


def test_standard_body_takes_precedence_over_direct_text_divs(work: Work, grobid: bytes) -> None:
    content = grobid.replace(
        b"<text><body>",
        b"<text><div><p>Legacy fallback must not override an existing research body."
        b"</p></div><body>",
    )
    assert prepare(work, XML_SOURCE, content) == prepare(work, XML_SOURCE, grobid)


def test_legacy_grobid_still_rejects_dtds_and_entities(work: Work, legacy_grobid: bytes) -> None:
    for declaration in (
        b'<!DOCTYPE html SYSTEM "https://example.test/external.dtd">',
        b'<!DOCTYPE html [<!ENTITY external SYSTEM "file:///private">]>',
    ):
        with pytest.raises(ValueError, match="unsafe or malformed GROBID XML"):
            prepare(work, XML_SOURCE, declaration + legacy_grobid)


def test_nested_sections_inline_text_and_long_blocks_preserve_words(work: Work) -> None:
    long_text = "Unchanged scholarly text with no paraphrases. " * 100
    xml = f"""<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>
    <head>Results</head><p>Stress was <hi>lower</hi> in the outdoor condition,
    according to participants.</p>
    <div><head>Subgroup</head><p>{long_text}</p></div>
    <p>Additional observations were collected during the same study period.</p>
    </div></body></text></TEI>""".encode()
    passages = prepare(work, XML_SOURCE, xml).passages
    assert (
        passages[0].text == "Stress was lower in the outdoor condition, according to participants."
    )
    assert passages[0].section == passages[-1].section == "Results"
    assert all(p.section == "Subgroup" for p in passages[1:-1])
    assert " ".join(p.text for p in passages[1:-1]) == long_text.strip()
    assert [p.passage_id for p in passages] == [f"p{i:04d}" for i in range(1, len(passages) + 1)]


@pytest.mark.parametrize(
    "content",
    [
        b"<TEI",
        b"<html>Not TEI</html>",
        b"<html><body><tei><text><div><p>Truncated legacy XML",
        b"<html><body><text><div><p>HTML prose without a TEI element is not scholarly XML."
        b"</p></div></text></body></html>",
        b"<html><body><tei><teiheader><abstract><p>Header abstract without a research body."
        b"</p></abstract></teiheader><text><abstract><p>Only an abstract is available.</p>"
        b"</abstract><back><div><p>Only bibliography text is available.</p></div></back>"
        b"</text></tei></body></html>",
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>'
        b"<p>Only abstract metadata.</p></teiHeader></TEI>",
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div>'
        b"<head>Heading only</head></div></body></text></TEI>",
        '<!DOCTYPE TEI [<!ENTITY x "expanded">]><TEI>&x;</TEI>'.encode("utf-16"),
    ],
)
def test_xml_without_usable_body_or_with_entities_is_rejected(work: Work, content: bytes) -> None:
    with pytest.raises(ValueError):
        prepare(work, XML_SOURCE, content)


def test_pdf_preparation_real_bytes_provenance_and_page_order(work: Work, pdf: bytes) -> None:
    document = prepare(work, PDF_SOURCE, pdf)
    assert document == prepare(work, PDF_SOURCE, pdf)
    assert document.work == work and document.source == PDF_SOURCE
    assert [(p.passage_id, p.section, p.text) for p in document.passages] == [
        ("p0001", None, METHODS),
        ("p0002", None, RESULTS),
    ]


@pytest.mark.parametrize("text", ["", "12345", "tiny text"])
def test_scanned_or_unusable_pdf_is_rejected(work: Work, make_pdf: MakePDF, text: str) -> None:
    with pytest.raises(ValueError):
        prepare(work, PDF_SOURCE, make_pdf((text,)))


def test_encrypted_and_corrupt_pdfs_are_rejected(work: Work, pdf: bytes) -> None:
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(pdf)))
    writer.encrypt("password")
    output = BytesIO()
    writer.write(output)
    for content in (b"<html>PDF error</html>", b"%PDF-1.4\nbroken\n%%EOF", output.getvalue()):
        with pytest.raises(ValueError):
            prepare(work, PDF_SOURCE, content)


@pytest.mark.parametrize(
    "bound",
    [
        "MAX_DOCUMENT_BYTES",
        "MAX_PDF_PAGES",
        "MAX_PDF_STREAM_BYTES",
        "MAX_TEXT_CHARACTERS",
    ],
)
def test_preparation_bounds(
    work: Work, pdf: bytes, bound: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("research_atlas.prepare." + bound, 1)
    with pytest.raises(ValueError):
        prepare(work, PDF_SOURCE, pdf)
