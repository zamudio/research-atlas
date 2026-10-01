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
metadata observations, immutable SourceDocument content, and accepted Extraction/Study/Finding
results. Batch/checkpoint commits and accepted evidence publication are atomic. Immutable content
and evidence remain addressable across retries and re-extraction. Run 001 remains UNEXECUTED.

```text
ResearchRequest -> ResearchRun -> SearchExecution -> observations -> Source
    -> SourceDocument -> Extraction -> Study -> Finding -> Insight -> useful outputs
```

Stage 4 adds validated synthesis from explicitly selected Findings, atomic immutable Insight
publication, seven bounded typed product reads, and a deterministic cited Markdown Evidence Brief.
Synthesis uses a caller-supplied provider-neutral implementation; no external LLM is bundled.
Atlas can acquire OpenAlex cached GROBID XML for one persisted run/Source at a time. The operation
requires the OpenAlex API key, resolves durable identifiers, bounds decoded XML to 32 MiB, retains
exact immutable bytes, and atomically records the document and run-specific processing outcome.
See [document acquisition](docs/providers.md#openalex-document-acquisition) for the callable.
Atlas can now execute one document extraction: deterministic GROBID XML projection creates an
immutable, anchorable text SourceDocument, then a structured-output provider supplies nested
Study/Finding candidates. Validated exact passages publish atomically with run selection and
processing state. Exact structured model output is retained, without the provider envelope or
hidden reasoning. The disposable local reference adapter uses Ollama and `qwen3.5:4b`; the model
and endpoint are configurable. See [extraction execution](docs/providers.md#local-extraction-execution).
SQLAlchemy Core, Psycopg and Alembic retain exactly 14 application relations. Concrete
synthesis-provider execution, broader run orchestration and frontend/API remain future work. OpenAlex remains
primary and Crossref optional;
Semantic Scholar and Zotero remain deferred.
See [synthesis and product access](docs/synthesis-and-product-access.md) for the callable workflow
and [database setup](docs/database.md) for configuration and migrations.

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
