"""Small discovery dry run; intentionally does not create a ResearchRun."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from research_atlas.application.discovery import (
    DiscoverSources,
    DiscoveryFailedError,
    serialize_report,
)
from research_atlas.application.ports.literature_source import LiteratureQuery, LiteratureSource
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.providers.openalex import OpenAlexLiteratureSource
from research_atlas.infrastructure.providers.semantic_scholar import (
    SemanticScholarLiteratureSource,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Discover and normalize a few sources for review")
    parser.add_argument("query", help="literature search query")
    parser.add_argument("--limit", type=int, default=8, choices=range(1, 11))
    parser.add_argument(
        "--semantic-scholar", action="store_true", help="also query the secondary provider"
    )
    parser.add_argument("--output", type=Path, help="optional ignored tmp/ or exports/ JSON path")
    return parser


async def run_dry_run(
    query_text: str,
    *,
    limit: int,
    include_semantic_scholar: bool,
    settings: ProviderSettings,
) -> str:
    providers: list[LiteratureSource] = [OpenAlexLiteratureSource(settings.openalex_api_key)]
    if include_semantic_scholar:
        providers.append(SemanticScholarLiteratureSource(settings.semantic_scholar_api_key))
    report = await DiscoverSources(providers).execute(LiteratureQuery(query_text, limit=limit))
    return json.dumps(serialize_report(report), indent=2, sort_keys=True) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = asyncio.run(
            run_dry_run(
                args.query,
                limit=args.limit,
                include_semantic_scholar=args.semantic_scholar,
                settings=ProviderSettings(),
            )
        )
    except DiscoveryFailedError as error:
        print(json.dumps(serialize_report(error.report), indent=2, sort_keys=True))
        print(str(error))
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
