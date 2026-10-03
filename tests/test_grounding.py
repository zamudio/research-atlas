import pytest

from research_atlas.grobid import project_grobid
from research_atlas.passages import MAX_PASSAGE_CHARACTERS, build_passage_index
from tests.test_extraction import OTHER, PASSAGE, XML


def test_projection_and_temporary_labels_are_deterministic() -> None:
    content = project_grobid(XML)
    assert content == f"{PASSAGE}\n\n{OTHER}\n".encode()
    index = build_passage_index(content)
    assert index == build_passage_index(project_grobid(XML))
    assert index.resolve("p0001") == PASSAGE
    with pytest.raises(ValueError, match="unknown"):
        index.resolve("p9999")


def test_projection_preserves_inline_text_order_and_normalizes_xml_whitespace() -> None:
    xml = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader>
    <fileDesc><titleStmt><title>Learning</title></titleStmt></fileDesc>
    <profileDesc><abstract><p>Abstract.</p></abstract></profileDesc></teiHeader>
    <text><body><div><head>Results</head><p> A <hi>small</hi> effect &amp; β.
    </p><p>Second.</p></div></body><back><p>Ignored references.</p></back></text></TEI>"""
    assert project_grobid(xml.encode()) == (
        "Learning\n\nAbstract.\n\nResults\n\nA small effect & β.\n\nSecond.\n".encode()
    )


@pytest.mark.parametrize(
    "xml",
    [
        b"",
        b"<TEI/>",
        b'<TEI xmlns="http://www.tei-c.org/ns/1.0"/>',
        b'<!DOCTYPE TEI [<!ENTITY x "secret">]><TEI>&x;</TEI>',
        '<!DOCTYPE TEI SYSTEM "file:///secret"><TEI/>'.encode("utf-16"),
    ],
)
def test_unsafe_or_unusable_xml_rejected(xml: bytes) -> None:
    with pytest.raises(ValueError):
        project_grobid(xml)


def test_oversized_xml_rejected() -> None:
    with pytest.raises(ValueError, match="bound"):
        project_grobid(b" " * (32 * 1024 * 1024 + 1))


def test_passages_preserve_unicode_whitespace_and_repetition() -> None:
    text = "Résultats ✓\n\n  No change — β.  \n\nRésultats ✓\n".encode()
    index = build_passage_index(text)
    assert dict(index.passages) == {
        "p0001": "Résultats ✓",
        "p0002": "  No change — β.  ",
        "p0003": "Résultats ✓",
    }
    with pytest.raises(TypeError):
        index.passages["p0001"] = "changed"  # pyright: ignore[reportIndexIssue]


@pytest.mark.parametrize(
    "content", [b"", b" \n\n\t\n", b"\xff", b"x" * (MAX_PASSAGE_CHARACTERS + 1)]
)
def test_invalid_passages_rejected(content: bytes) -> None:
    with pytest.raises(ValueError):
        build_passage_index(content)
