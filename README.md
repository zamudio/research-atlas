# Research Atlas

Research Atlas is being built to research a question, discover publications, extract study
findings, and serve evidence-backed insights with useful outputs. It remains reusable across
research domains; AI Tutor is one downstream use case.

## Implemented today

The metadata-only dry-run searches OpenAlex and optionally Crossref, reconciles exact Source
identities, and reports provider outcomes and attributable publication metadata. It does not
create a research run, obtain paper content, extract findings, or synthesize evidence.

The small retained model distinguishes a research request, actual run/search records, Sources,
Studies, and Findings. Source identity is Atlas-owned; provider records and external identifiers
are matching evidence. Bibliographic credits remain provider metadata without contributor identity.

## Product direction

```text
Research question -> research run -> scholarly discovery -> Source
    -> paper content -> Studies and Findings -> evidence-linked Insights -> useful outputs
```

Paper-content acquisition, validated extraction, persistence, Insight synthesis, and frontend
access are future stages. Stage 1 removes speculative architecture without implementing them.
The Learning Foundations request (Run 001) remains unexecuted.

## Development

Requires Python 3.14.7 and uv. After dependency changes, refresh the lockfile before locked setup.

```shell
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

- [Architecture](docs/architecture.md)
- [Research lifecycle](docs/research-lifecycle.md)
- [Provider behavior and limitations](docs/providers.md)
- [Dry-run CLI](docs/cli.md)
- [Documentation index](docs/index.md)
