import pytest

from research_atlas.application.grobid_text import prepare_grobid_text
from research_atlas.application.passage_index import (
    MAX_PASSAGE_CHARACTERS,
    PASSAGE_INDEX_VERSION,
    build_passage_index,
)
from tests.unit.test_extraction import PASSAGE, PASSAGE_ID, XML, xml_document


def test_index_reconstructs_stable_ids_text_and_exact_projected_blocks() -> None:
    _, content = prepare_grobid_text(xml_document(), XML)
    index = build_passage_index(content)
    repeated = build_passage_index(bytes(bytearray(content)), version=index.version)
    assert index == repeated
    assert index.version == PASSAGE_INDEX_VERSION == "atlas.passage-index.v1"
    assert tuple(index.passages) == ("p0001", "p0002", "p0003", "p0004")
    assert (
        index.model_text
        == repeated.model_text
        == (
            "[p0001] Learning study\n\n[p0002] We studied learning.\n\n"
            f"[p0003] Results\n\n[{PASSAGE_ID}] {PASSAGE}\n"
        )
    )
    assert index.resolve(PASSAGE_ID) == PASSAGE
    assert all(text.strip() and text.encode("utf-8") in content for text in index.passages.values())


def test_index_preserves_unicode_whitespace_and_repeated_passage_order() -> None:
    content = "Résultats ✓\n\n  No change — β.  \n\nRésultats ✓\n".encode()
    index = build_passage_index(content)
    assert dict(index.passages) == {
        "p0001": "Résultats ✓",
        "p0002": "  No change — β.  ",
        "p0003": "Résultats ✓",
    }
    assert index.resolve("p0001") == index.resolve("p0003")
    assert all(text.encode() in content for text in index.passages.values())


def test_index_mapping_is_immutable() -> None:
    index = build_passage_index(b"Results\n")
    with pytest.raises(TypeError):
        index.passages["p0001"] = "invented"  # pyright: ignore[reportIndexIssue]


def test_index_skips_blank_blocks_and_keeps_remaining_ids_sequential() -> None:
    index = build_passage_index(b"\n\nResults\n\n \t\n\nNo change.\n")
    assert dict(index.passages) == {"p0001": "Results", "p0002": "No change."}


def test_passage_bound_keeps_whole_blocks_and_rejects_oversize_without_chunking() -> None:
    content = ("é" * MAX_PASSAGE_CHARACTERS + "\n").encode()
    index = build_passage_index(content)
    assert len(index.passages) == 1 and index.resolve("p0001").encode() == content[:-1]
    with pytest.raises(ValueError, match="passage bound"):
        build_passage_index(("é" * (MAX_PASSAGE_CHARACTERS + 1) + "\n").encode())


@pytest.mark.parametrize("content", [b"", b" \n\n\t\n", b"\xff"])
def test_index_rejects_blank_or_non_utf8_prepared_content(content: bytes) -> None:
    with pytest.raises(ValueError):
        build_passage_index(content)


def test_index_rejects_unknown_versions_and_ids() -> None:
    with pytest.raises(ValueError, match="version"):
        build_passage_index(b"Results\n", version="atlas.passage-index.v99")
    index = build_passage_index(b"Results\n")
    for passage_id in ("p0000", "p0002", "p1", "invented"):
        with pytest.raises(ValueError, match="unknown"):
            index.resolve(passage_id)


def test_ids_remain_distinct_after_four_digits() -> None:
    index = build_passage_index(b"\n\n".join([b"Results"] * 10_001) + b"\n")
    assert tuple(index.passages)[-3:] == ("p9999", "p10000", "p10001")
