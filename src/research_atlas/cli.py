"""Machine-readable CLI over the same Python evidence workflow."""

import argparse
import asyncio
import sys

import httpx
from pydantic import ValidationError

from research_atlas.pipeline import evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="atlas", description="Retrieve scholarly source passages."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("evidence", help="Acquire full text and return ranked passages.")
    command.add_argument("question")
    command.add_argument("--max-papers", type=int, default=3, metavar="N")
    arguments = parser.parse_args()
    try:
        result = asyncio.run(evidence(arguments.question, max_papers=arguments.max_papers))
    except ValidationError:
        print(
            "atlas: invalid configuration or OpenAlex response; check your API key and settings.",
            file=sys.stderr,
        )
        return 1
    except (ValueError, httpx.HTTPError, TimeoutError) as error:
        # Provider response bodies and authenticated URLs never enter CLI diagnostics.
        message = (
            str(error) if isinstance(error, ValueError) else "OpenAlex discovery request failed."
        )
        print(f"atlas: {message}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
