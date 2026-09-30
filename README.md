# Research Atlas

Research Atlas is being built to research a question, discover publications, extract study
findings, and serve evidence-backed Insights. It remains reusable across research domains;
AI Tutor is one downstream use case.

## Implemented today

The metadata diagnostic searches OpenAlex and optional Crossref in bounded batches. It validates
provider responses, preserves whole attributable metadata observations, reconciles exact Source
identity, and exposes partial searches, retry checkpoints, and isolated identity conflicts.
Display metadata comes from one identified observation, never a mixture of provider fields.

PostgreSQL persistence now retains runs, bounded search batches, reconciled Sources, complete
metadata observations, supplied SourceDocument content, and accepted Extraction/Study/Finding
results. Batch/checkpoint commits and accepted evidence publication are atomic. Immutable content
and evidence remain addressable across retries and re-extraction. Run 001 remains UNEXECUTED.

```text
ResearchRequest -> ResearchRun -> SearchExecution -> observations -> Source
    -> SourceDocument -> Extraction -> Study -> Finding -> Insight -> useful outputs
```

Stage 3 implements the [documented persistence semantics](docs/persistence-boundary.md) with
SQLAlchemy Core, Psycopg and Alembic. Insight tables exist for integrity only. There is no document
acquisition, extraction execution, LLM call, synthesis generation, frontend/API or generated output.
See [database setup and operations](docs/database.md) for configuration and the callable slice.

## Development

Requires Python 3.14.7 and uv; persistence requires PostgreSQL (CI uses PostgreSQL 18).

```shell
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

PostgreSQL tests skip explicitly unless `RESEARCH_ATLAS_TEST_DATABASE_URL` is set. CI upgrades
the schema, checks migration drift, and runs PostgreSQL acceptance tests.

- [Database setup](docs/database.md)
- [Architecture](docs/architecture.md)
- [Research lifecycle](docs/research-lifecycle.md)
- [Providers and checkpoints](docs/providers.md)
- [Dry-run CLI](docs/cli.md)
- [Documentation index](docs/index.md)
