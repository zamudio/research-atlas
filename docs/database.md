# PostgreSQL development and the durable slice

The durable slice uses SQLAlchemy 2.0 Core with async Psycopg 3 connections, SQLAlchemy's normal pool,
and Alembic migrations. It has exactly 14 application tables. CI uses PostgreSQL 18. There is
no alternative SQLite acceptance path, extra driver, repository hierarchy or job framework.

## Configuration and migrations

Set `RESEARCH_ATLAS_DATABASE_URL` in the process environment to a PostgreSQL Psycopg URL
(`postgresql+psycopg://USER:PASSWORD@HOST/DATABASE`). Keep real credentials outside Git.
`.env.example` lists the variable names; database settings do not implicitly load a `.env` file.
Export the variables through your shell or secret manager. Provider configuration remains separate.

```shell
uv sync --locked
uv run alembic upgrade head
uv run alembic check
```

Alembic uses `RESEARCH_ATLAS_TEST_DATABASE_URL` when explicitly set, otherwise the runtime URL.
The initial revision is `0001_lean_persistence`. It creates the schema with frozen migration
operations, not `metadata.create_all()`. Live Core `target_metadata` enables drift checking.
Stage 4 adds `0002_insight_publication`; `0001_lean_persistence` is unchanged. CI explicitly upgrades
to 0001 and then head before running `alembic check`. Existing schema-only Insights remain drafts;
the migration does not manufacture configuration bytes or certify them as published.
Downgrade is destructive schema removal intended only for disposable development databases.

`create_database_engine()` validates the Psycopg URL and returns an unconnected async engine.
It uses READ COMMITTED for unique-key retry visibility. The caller must `await engine.dispose()`.
No engine or global Windows event-loop policy is created at import time.

## Operation-oriented entry points

All public persistence operations own a short transaction and accept trusted domain inputs.
They return IDs/small results, never ORM model graphs. They are available from:

| Module under `research_atlas.infrastructure.persistence` | Operations |
| --- | --- |
| `runs` | `create_project`, `create_research_run`, `start_search_execution` |
| `discovery` | `DiscoveryPersistence.load_search_resume_state`, `commit_discovery_batch`, `record_search_failure` |
| `evidence` | `record_source_document`, `load_source_document`, `record_extraction`, `publish_accepted_extraction`, `select_run_source_extraction`, `set_processing_state`, `apply_screening_decision`, `DocumentAcquisitionPersistence.load_acquisition_identity`, `commit_document_acquisition` |
| `insights` | `PostgresInsightPublication.load_evidence`, `publish` |
| `reads` | `run_progress`, `run_sources`, `source_detail`, `insight_detail`, `insight_evidence`, `study_context`, `output_insights` |

Create a project, a ResearchRun retaining the original request, and a running SearchExecution with
exact provider/operation/query/ordered parameters and batch limit. Then use the application callable:

```python
from research_atlas.application.durable_ingestion import ingest_one_batch
from research_atlas.application.ports.literature_source import LiteratureSource
from research_atlas.infrastructure.persistence.database import create_database_engine
from research_atlas.infrastructure.persistence.discovery import DiscoveryPersistence


async def process_one(search_id: str, provider: LiteratureSource) -> None:
    engine = create_database_engine()
    try:
        await ingest_one_batch(DiscoveryPersistence(engine), search_id, provider)
    finally:
        await engine.dispose()
```

The provider must match the persisted operation. HTTP happens after the resume-state read has
closed and before the commit transaction opens. The callable processes one page, with no queue,
lease or automatic unbounded loop. It returns `None` for an already completed search.

On successful persistence, the batch receipt includes resolved Source IDs, durable observation IDs,
conflicted positions and continuation. The search outcome is `partial` until exhausted. On a provider
failure, prior batches remain committed and safe error metadata is recorded separately. Retry by
loading the durable checkpoint again. A transaction error leaves it unchanged. `ReplayMismatch`
means an already committed page was presented with different content; `CheckpointConflict` means
the caller must reload current progress. Neither condition silently skips or overwrites a page.

`record_source_document` accepts exact supplied bytes and verifies their checksum. It returns the
stored document UUID, which may be an earlier identical usable version. Use that returned ID for
extraction provenance. Read operations recheck content SHA-256. New representations use new IDs.

`record_extraction` stores supplied queued/running/failed/review-needed/rejected attempts.
`publish_accepted_extraction` accepts an accepted Extraction, exact configuration bytes, Studies and
Findings. It verifies checksum, run/Source/document ownership and exact UTF-8 passage anchors. All
rows publish together or none do. Locator-only anchors are allowed in draft domain records but
cannot be published as accepted evidence. Exact retry of finalized evidence is idempotent; changed
output under the same extraction UUID raises `ImmutableRecordConflict`. Re-extraction uses new IDs.

Selection accepts an accepted extraction for the same Source, including reuse from another creating
run as permitted in Stage 2. It does not change processing state. Record `extracted` explicitly after
selection. A later `failed` state leaves the selection intact. Current source screening is stored
on run_sources; exclusion atomically records `excluded`. Study-scoped screening does not exclude the
whole Source. No screening history table is created.

## Tests and isolation

Set `RESEARCH_ATLAS_TEST_DATABASE_URL` explicitly to a dedicated disposable PostgreSQL test database.
Tests never fall back to runtime credentials. Each PostgreSQL test creates its own randomly named
schema, applies the actual Alembic migration, and removes only that schema after the test. The test
user therefore needs permission to create schemas. No test depends on another test's rows.

```shell
uv run alembic upgrade head
uv run alembic check
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Without the test URL, PostgreSQL tests skip explicitly; ordinary tests and offline migration SQL
rendering still run. Offline rendering is not a substitute for executing PostgreSQL constraints,
triggers, concurrency or migration drift checks. CI supplies a dedicated PostgreSQL 18 service and
runs migrations, drift checks, tests, lint, formatting and types. No container is launched by tests.

Psycopg async connections require a selector-compatible event loop on Windows. PostgreSQL tests
use a test-local `asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)` there. Applications choose
their compatible loop at entry; importing Atlas never mutates global loop policy.

The isolated Codex bootstrap selects `.codex-local/venv`; the repository's usual Pyright `.venv`
setting requires the established local override in that environment:

```powershell
. .\.codex-local\bootstrap.ps1
$env:PATH = (Join-Path $PWD '.codex-local\venv\Scripts') + [IO.Path]::PathSeparator + $env:PATH
node .\.codex-local\venv\Lib\site-packages\pyright\dist\index.js --venvpath .\.codex-local
```

Insight publication retains status, publication timestamp, exact configuration BYTEA and canonical
publication digest on the existing `insights` relation. It checks run existence, exact configuration
hash, complete unique evidence selection, and at least one supporting rationale. Each linked Finding
must resolve through the accepted extraction currently selected for its Source in the producing run.
Membership row locks serialize publication validation with selection changes. The proposal/synthesis
call happens outside this transaction. Exact historical retry checks the retained publication digest
before active selection, so a retry does not fail merely because the run later selected new evidence.

The transaction inserts a draft, links its complete bounded evidence set, then marks it published.
Other transactions see all or none. A trigger blocks updates/deletes of published Insights; another
locks the parent and blocks any changes to published relationships. Publication requires supporting
evidence and at most 100 links. The configuration checksum and producing provenance are SQL checks.
Changed content/configuration/provenance under an existing UUID raises `ImmutableRecordConflict`.
Legacy drafts are inspectable but cannot be passed to output generation or overwritten by publication;
deliberately publish a new UUID after validating the proposal.

No new index or table is required: the existing run, relationship composite primary key and Finding
FK indexes serve Stage 4 reads. Multi-query product reads use a REPEATABLE READ snapshot; normal writes
retain READ COMMITTED. Query-count acceptance tests cover all seven reads at sizes 5 and 10; tests also
cover invalid proposals/publication rollback, immutable history, selection races between packet load
and publication, mixed/null evidence, dependence warnings, citations and pagination/isolation.

See [synthesis and product access](synthesis-and-product-access.md) for exact bounds and callables.
The [OpenAlex acquisition callable](providers.md#openalex-document-acquisition) loads durable Work
identity, retrieves bounded cached GROBID XML outside PostgreSQL transactions, then atomically records
the immutable SourceDocument and run processing state. Existing usable-version deduplication and
immutability remain intact; no schema or migration change is needed.
Extraction execution, concrete synthesis-provider execution, API/frontend and generated
recommendation/prompt services remain unimplemented. Run 001 remains UNEXECUTED.
