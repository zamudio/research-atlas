"""Deterministic BM25 passage ranking; the score measures lexical relevance only."""

import re
import unicodedata
from collections import Counter
from math import log1p

from research_atlas.models import Document, Evidence

_STOPWORDS = frozenset(
    "a an and are as at be been being by can could did do does for from had has have how "
    "i if in into is it its may of on or our should than that the their them there these "
    "they this those to was we were what when where which who why will with would you your".split()
)
_MAX_EVIDENCE = 3


def _tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return [word for word in re.findall(r"[^\W_]+", normalized) if word not in _STOPWORDS]


def rank_passages(question: str, document: Document) -> tuple[Evidence, ...]:
    query = sorted(set(_tokens(question)))
    frequencies = [Counter(_tokens(passage.text)) for passage in document.passages]
    lengths = [sum(frequency.values()) for frequency in frequencies]
    average = sum(lengths) / len(lengths) if lengths else 0
    if not query or not average:
        return ()
    document_frequency = Counter(term for frequency in frequencies for term in frequency)
    ranked: list[Evidence] = []
    for passage, frequency, length in zip(document.passages, frequencies, lengths, strict=True):
        score = 0.0
        for term in query:
            count = frequency[term]
            if count:
                inverse_frequency = log1p(
                    (len(frequencies) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                score += (
                    inverse_frequency
                    * count
                    * 2.5
                    / (count + 1.5 * (0.25 + 0.75 * length / average))
                )
        if score > 0:
            ranked.append(
                Evidence(
                    passage_id=passage.passage_id,
                    section=passage.section,
                    text=passage.text,
                    score=score,
                )
            )
    # Stable sorting preserves source order on ties. Zero-overlap passages are omitted.
    ranked.sort(key=lambda item: item.score, reverse=True)
    return tuple(ranked[:_MAX_EVIDENCE])
