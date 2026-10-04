"""Collect grounded evidence from a bounded, sequential review of scholarly papers."""

from research_atlas.embeddings import Embedder
from research_atlas.extraction import extract_evidence
from research_atlas.models import EvidenceReview, SourceEvidence
from research_atlas.openalex import DEFAULT_ELIGIBLE_POOL_TARGET, OpenAlex
from research_atlas.providers import StructuredModel


async def collect_evidence(
    question: str,
    *,
    literature: OpenAlex,
    model: StructuredModel,
    embedder: Embedder | None = None,
    max_sources: int = 20,
) -> EvidenceReview:
    """Rank content-eligible lexical hits, then review up to max_sources usable papers."""
    if type(question) is not str or not question.strip() or len(question) > 2000:
        raise ValueError("question must be nonblank text of at most 2000 characters")
    if type(max_sources) is not int or not 1 <= max_sources <= DEFAULT_ELIGIBLE_POOL_TARGET:
        raise ValueError(
            f"max_sources must be an integer between 1 and {DEFAULT_ELIGIBLE_POOL_TARGET}"
        )

    candidates = await literature.search(
        question, limit=DEFAULT_ELIGIBLE_POOL_TARGET, embedder=embedder
    )
    reviewed_sources = 0
    sources: list[SourceEvidence] = []
    for candidate in candidates:
        content = await literature.fetch_content(candidate)
        if content is None:
            continue

        result = await extract_evidence(
            question=question,
            source=candidate.source,
            content=content,
            model=model,
            embedder=embedder,
        )
        reviewed_sources += 1
        if result.evidence:
            sources.append(result)
        if reviewed_sources == max_sources:
            break

    return EvidenceReview(question, reviewed_sources, tuple(sources))
