"""Collect grounded evidence from a bounded, sequential review of scholarly papers."""

from research_atlas.extraction import extract_evidence
from research_atlas.models import EvidenceReview, SourceEvidence
from research_atlas.openalex import OpenAlex, OpenAlexError
from research_atlas.providers import StructuredModel


async def collect_evidence(
    question: str,
    *,
    literature: OpenAlex,
    model: StructuredModel,
    max_sources: int = 20,
) -> EvidenceReview:
    """Review usable papers in search order; retain only papers contributing evidence."""
    if type(question) is not str or not question.strip() or len(question) > 2000:
        raise ValueError("question must be nonblank text of at most 2000 characters")
    if type(max_sources) is not int or not 1 <= max_sources <= 50:
        raise ValueError("max_sources must be an integer between 1 and 50")

    candidates = await literature.search(question, limit=min(50, max_sources * 2), semantic=True)
    reviewed_sources = 0
    sources: list[SourceEvidence] = []
    for source in candidates:
        try:
            content = await literature.fetch_content(source)
        except OpenAlexError as error:
            if error.code == "content_size_exceeded":
                continue
            raise
        if content is None:
            continue

        result = await extract_evidence(
            question=question, source=source, content=content, model=model
        )
        reviewed_sources += 1
        if result.evidence:
            sources.append(result)
        if reviewed_sources == max_sources:
            break

    return EvidenceReview(question, reviewed_sources, tuple(sources))
