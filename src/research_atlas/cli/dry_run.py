"""Small discovery dry run; intentionally does not create a ResearchRun."""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import (
    LiteratureQuery,
    LiteratureSearchRequest,
)
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers._http import AttemptObserver, RequestAttemptEvent
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_atlas.infrastructure.providers.semantic_scholar import (
    SemanticScholarBulkSearch,
    SemanticScholarRelevanceSearch,
)
from research_atlas.infrastructure.providers.semantic_scholar_ownership import (
    SemanticScholarOwnershipError,
    SemanticScholarOwnershipGuard,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover and normalize a few sources for review")
    parser.add_argument("query", help="OpenAlex search query")
    parser.add_argument("--limit", type=int, default=8, choices=range(1, 11))
    parser.add_argument(
        "--semantic-scholar-relevance",
        metavar="QUERY",
        help="also run S2 plain-text relevance search with this exact query",
    )
    parser.add_argument(
        "--semantic-scholar-bulk",
        metavar="QUERY",
        help="also run S2 Boolean/bulk search with this exact query",
    )
    parser.add_argument("--output", type=Path, help="optional ignored tmp/ or exports/ JSON path")
    parser.add_argument(
        "--diagnose-s2-requests",
        action="store_true",
        help="print secret-safe S2 physical-attempt telemetry to stderr",
    )
    return parser


def _diagnostic_observer() -> AttemptObserver:
    first_start: float | None = None

    def observe(event: RequestAttemptEvent) -> None:
        nonlocal first_start
        if first_start is None:
            first_start = event.monotonic_start
        status = "transport" if event.response_status is None else str(event.response_status)
        retry = event.retry_reason or "none"
        delay = "none" if event.retry_delay is None else f"{event.retry_delay:.3f}s"
        print(
            "S2 attempt "
            f"operation={event.operation_id} endpoint={event.endpoint_path} "
            f"attempt={event.attempt_number} start=+{event.monotonic_start - first_start:.3f}s "
            f"status={status} retry={retry} delay={delay}",
            file=sys.stderr,
        )

    return observe


async def run_dry_run(
    query_text: str,
    *,
    limit: int,
    settings: ProviderSettings,
    semantic_scholar_relevance_query: str | None = None,
    semantic_scholar_bulk_query: str | None = None,
    s2_attempt_observer: AttemptObserver | None = None,
    ownership_guard_factory: Callable[[], AbstractContextManager[object]] = (
        SemanticScholarOwnershipGuard
    ),
) -> str:
    uses_semantic_scholar = (
        semantic_scholar_relevance_query is not None or semantic_scholar_bulk_query is not None
    )
    searches = [
        LiteratureSearchRequest(
            OpenAlexLiteratureSource(settings.openalex_api_key),
            LiteratureQuery(query_text, limit=limit),
        )
    ]
    if semantic_scholar_relevance_query is not None:
        searches.append(
            LiteratureSearchRequest(
                SemanticScholarRelevanceSearch(
                    settings.semantic_scholar_api_key,
                    attempt_observer=s2_attempt_observer,
                ),
                LiteratureQuery(semantic_scholar_relevance_query, limit=limit),
            )
        )
    if semantic_scholar_bulk_query is not None:
        searches.append(
            LiteratureSearchRequest(
                SemanticScholarBulkSearch(
                    settings.semantic_scholar_api_key,
                    attempt_observer=s2_attempt_observer,
                ),
                LiteratureQuery(semantic_scholar_bulk_query, limit=limit),
            )
        )
    guard = ownership_guard_factory() if uses_semantic_scholar else nullcontext()
    with guard:
        report = await DiscoverSources(searches).execute()
    return json.dumps(serialize_report(report), indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = asyncio.run(
            run_dry_run(
                args.query,
                limit=args.limit,
                semantic_scholar_relevance_query=args.semantic_scholar_relevance,
                semantic_scholar_bulk_query=args.semantic_scholar_bulk,
                s2_attempt_observer=(_diagnostic_observer() if args.diagnose_s2_requests else None),
                settings=ProviderSettings(),
            )
        )
    except DiscoveryFailedError as error:
        print(json.dumps(serialize_report(error.report), indent=2, sort_keys=True))
        print(str(error))
        return 1
    except SemanticScholarOwnershipError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
