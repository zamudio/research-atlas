# Research Atlas

Research Atlas is being built to research a question, discover publications, extract study
findings, and serve evidence-backed Insights. It remains reusable across research domains;
AI Tutor is one downstream use case.

## Implemented today

The metadata diagnostic searches OpenAlex and optional Crossref in bounded batches. It validates
provider responses, preserves whole attributable metadata observations, reconciles exact Source
identity, and exposes partial searches, retry checkpoints, and isolated identity conflicts.
Display metadata comes from one identified observation, never a mixture of provider fields.

Small trusted contracts now describe SourceDocument versions, Extraction attempts, Study/Finding
content provenance, and Insight/Finding relationships. They do not download content, execute
extraction, generate synthesis, or persist research. Run 001 remains UNEXECUTED.

```text
ResearchRequest -> ResearchRun -> SearchExecution -> observations -> Source
    -> SourceDocument -> Extraction -> Study -> Finding -> Insight -> useful outputs
```

Stage 3 will implement the [documented persistence semantics](docs/persistence-boundary.md).
Later stages provide content acquisition, extraction/synthesis execution, and frontend access.

## Development

Requires Python 3.14.7 and uv. The lockfile is current; no new Stage 2 dependencies are required.

```shell
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

- [Architecture](docs/architecture.md)
- [Research lifecycle](docs/research-lifecycle.md)
- [Providers and checkpoints](docs/providers.md)
- [Dry-run CLI](docs/cli.md)
- [Documentation index](docs/index.md)
