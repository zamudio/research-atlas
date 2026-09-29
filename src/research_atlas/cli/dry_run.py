"""Small discovery dry run; intentionally does not create a ResearchRun."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
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
from research_atlas.infrastructure.providers.crossref import CrossrefWorksSearch
from research_atlas.infrastructure.providers.openalex import (
    OpenAlexLiteratureSource,
    OpenAlexSemanticSearch,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover and normalize a few sources for review")
    parser.add_argument("query", help="OpenAlex search query")
    parser.add_argument("--limit", type=int, default=8, choices=range(1, 11))
    parser.add_argument(
        "--openalex-semantic",
        metavar="QUERY",
        help="also run OpenAlex semantic discovery with this exact natural-language query",
    )
    parser.add_argument(
        "--crossref-bibliographic",
        metavar="QUERY",
        help="also run optional Crossref bibliographic lookup with this exact query",
    )
    parser.add_argument("--output", type=Path, help="optional tmp/ or exports/ JSON path")
    return parser


async def run_dry_run(
    query_text: str,
    *,
    limit: int,
    settings: ProviderSettings,
    openalex_semantic_query: str | None = None,
    crossref_bibliographic_query: str | None = None,
) -> str:
    searches = [
        LiteratureSearchRequest(
            OpenAlexLiteratureSource(settings.openalex_api_key),
            LiteratureQuery(query_text, limit=limit),
        )
    ]
    if openalex_semantic_query is not None:
        searches.append(
            LiteratureSearchRequest(
                OpenAlexSemanticSearch(settings.openalex_api_key),
                LiteratureQuery(openalex_semantic_query, limit=limit),
            )
        )
    if crossref_bibliographic_query is not None:
        searches.append(
            LiteratureSearchRequest(
                CrossrefWorksSearch(mailto=settings.crossref_mailto),
                LiteratureQuery(crossref_bibliographic_query, limit=limit),
            )
        )
    report = await DiscoverSources(searches).execute()
    return json.dumps(serialize_report(report), indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        output = asyncio.run(
            run_dry_run(
                args.query,
                limit=args.limit,
                openalex_semantic_query=args.openalex_semantic,
                crossref_bibliographic_query=args.crossref_bibliographic,
                settings=ProviderSettings(),
            )
        )
    except DiscoveryFailedError as error:
        print(json.dumps(serialize_report(error.report), indent=2, sort_keys=True))
        print(str(error), file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
