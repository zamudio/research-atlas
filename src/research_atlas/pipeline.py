"""The one public workflow: question to acquired, inspectable source passages."""

import httpx

from research_atlas.acquire import acquire
from research_atlas.config import Settings
from research_atlas.evidence import rank_passages
from research_atlas.models import EvidenceResult, Failure, PaperEvidence
from research_atlas.openalex import MAX_CANDIDATES, discover


async def evidence(
    question: str, *, max_papers: int = 3, settings: Settings | None = None
) -> EvidenceResult:
    """Inspect at most 50 candidates, stopping after max_papers prepared papers.

    Papers retain OpenAlex order. Each has up to three passages in descending BM25
    order (ties in source order); no lexical overlap yields an empty evidence tuple.
    Paper failures are returned; invalid input/configuration and discovery errors raise.
    """
    if type(question) is not str or not question.strip() or len(question) > 2000:
        raise ValueError("question must be nonblank and at most 2000 characters")
    if type(max_papers) is not int or not 1 <= max_papers <= MAX_CANDIDATES:
        raise ValueError(f"max_papers must be an integer between 1 and {MAX_CANDIDATES}")
    settings = settings if settings is not None else Settings.from_env()
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
        works, discovery_failures = await discover(question, client, settings)
        papers: list[PaperEvidence] = []
        failures = list(discovery_failures)
        for work in works:
            document = await acquire(work, client, settings)
            if isinstance(document, Failure):
                failures.append(document)
                continue
            papers.append(
                PaperEvidence(
                    work=document.work,
                    source=document.source,
                    evidence=rank_passages(question, document),
                )
            )
            if len(papers) == max_papers:
                break
    return EvidenceResult(question=question, papers=tuple(papers), failures=tuple(failures))
