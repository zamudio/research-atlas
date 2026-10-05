from math import isclose, log1p

import pytest

from research_atlas.evidence import rank_passages
from research_atlas.models import ContentSource, Document, Passage, Work
from research_atlas.prepare import prepare


def test_bm25_ranking_exact_text_and_bounded_ties(work: Work) -> None:
    texts = [
        "Unrelated astronomy.",
        "Stress stress outside.",
        "Stress unrelated wording.",
        "Stress stress outside.",
        "Stress stress outside.",
        "Stress stress outside.",
    ]
    document = Document(
        work=work,
        source=ContentSource(kind="oa_pdf", url="https://oa.test/paper"),
        passages=tuple(
            Passage(passage_id=f"p{i:04d}", section=None, text=text)
            for i, text in enumerate(texts, 1)
        ),
    )
    ranked = rank_passages("Does outside reduce stress?", document)
    assert ranked == rank_passages("Does outside reduce stress?", document)
    assert [item.passage_id for item in ranked] == ["p0002", "p0004", "p0005"]
    for item in ranked:
        passage = next(p for p in document.passages if p.passage_id == item.passage_id)
        assert item.text == passage.text and item.section == passage.section
        assert item.score > 0


def test_bm25_score_is_retrieval_math_not_a_probability(work: Work) -> None:
    document = Document(
        work=work,
        source=ContentSource(kind="oa_pdf", url="https://oa.test/paper"),
        passages=(
            Passage(passage_id="p0001", section=None, text="stress stress"),
            Passage(passage_id="p0002", section=None, text="irrelevant astronomy"),
        ),
    )
    result = rank_passages("stress", document)
    assert len(result) == 1
    assert isclose(result[0].score, log1p(1.5 / 1.5) * 2 * 2.5 / (2 + 1.5))


@pytest.mark.parametrize("question", ["astronomy", "the and does", "?!"])
def test_zero_overlap_never_returns_arbitrary_passages(
    work: Work, grobid: bytes, question: str
) -> None:
    document = prepare(work, ContentSource(kind="grobid_xml", url="https://oa.test/xml"), grobid)
    assert rank_passages(question, document) == ()


def test_normalization_only_affects_matching_not_source_text(work: Work) -> None:
    text = "Café participants reported STRESS; the source wording stays intact."
    document = Document(
        work=work,
        source=ContentSource(kind="oa_pdf", url="https://oa.test/paper"),
        passages=(Passage(passage_id="p0001", section="Results", text=text),),
    )
    result = rank_passages("ＣＡＦÉ stress", document)
    assert result[0].text == text and result[0].section == "Results"
