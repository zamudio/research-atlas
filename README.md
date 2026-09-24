# Research Atlas

Research Atlas is a reusable, provenance-first foundation for turning research into
reviewable product decisions. Version 0.4.6 adds PowerShell-safe Semantic Scholar bulk-query input
to the v0.4 provider/ingestion foundation while keeping the v0.3 records schema frozen.

## Core/project boundary

Research Atlas core is domain-neutral infrastructure. A new research project must be usable by
supplying project and run data without modifying `src/research_atlas`, the generic record schema,
or provider logic.

- `project_id` is an opaque namespace carried through records and exports. Core code must never
  branch on its value.
- `run_id` is the identity of a research run. It remains unique within a validated
  `ResearchRecords` collection and is referenced by provenance and export manifests; it is not a
  behavior switch.
- Search queries, research questions, inclusion and exclusion rules, project vocabulary, and
  product destinations are project/run data, not core logic.
- `ArchitectureCandidate.proposed_destination` and `ProductImplication.destination` are generic
  strings populated from project configuration. Destinations such as `state`, `policy`,
  `curriculum`, `telemetry`, or `ux` are not core enums.
- Product translation is a separate, optional stage. It may create architecture candidates and
  product implications that reference an `EvidenceAssessment`, but it must not mutate or rewrite
  that underlying assessment.

Project-owned definitions live under `projects/`. Nothing in core imports them.

## What it is

- A normalized internal representation for bibliographic sources, studies, constructs,
  measurements, interventions, findings, evidence assessments, and product implications.
- A versioned protocol for extracting, assessing, and promoting research into product guidance.
- A producer of static, versioned export bundles that consumer projects can import without a
  runtime dependency on this package.

## What it is not

It is not a paper database replacement, an Elicit clone, a scientific authority, a web UI, an
agent framework, or a claim that qualitative review can be reduced to one universal score.

OpenAlex is the primary programmatic discovery provider, Semantic Scholar is a secondary
discovery/enrichment provider, and Zotero is the canonical reference library. Provider-specific
models stop at application-owned ports. Elicit free/basic may be used manually, but automated
Elicit integration is deferred: this project does not scrape or browser-automate around plan or
API limits. A future Elicit export or API importer can use the same ingestion boundary.

Consumer projects receive curated exports. They do not import or run Research Atlas in
production.

## Lifecycle

1. Define a consumer-aware `ProjectProfile`.
2. Conduct versioned research runs using an approved protocol and taxonomy.
3. Normalize publications into source records, then separate studies or analyses.
4. Extract studies, constructs, measurements, interventions, and study-level findings with required
   process provenance tied to the creating research run.
5. Synthesize findings into claim-centered evidence assessments, optionally linking relevant
   constructs.
6. When a project calls for product translation, review architecture candidates and product
   implications without changing the underlying evidence assessments.
7. Publish a checksummed, versioned static export bundle.

Export manifests are accepted only when every contributing run is bundled and matches the
manifest's project ID, protocol versions, and taxonomy version.

## Repository map

- `src/research_atlas/domain`: trusted internal dataclasses.
- `src/research_atlas/schemas`: validated import, configuration, and record boundaries.
- `src/research_atlas/application/ports`: provider-neutral acquisition interfaces.
- `src/research_atlas/application/source_identity.py`: stable identity and exact-ID merging.
- `src/research_atlas/infrastructure/providers`: OpenAlex, Semantic Scholar, and Zotero
  adapters.
- `src/research_atlas/application/export`: static bundle contracts and checksums.
- `protocol`: independently versioned generic extraction, evidence, and promotion guidance.
- `projects`: project-owned profiles and planned run definitions; core never imports them.

Raw PDFs, corpora, provider dumps, and generated exports are intentionally ignored by Git.

## Provider dry run

The dry run discovers and normalizes publications with `--limit` applied per requested operation,
so three operations at `--limit 10` may return up to 30 sources before exact-ID deduplication. It
does not create `ResearchRun`, study, finding, evidence, architecture, or product records, and it
does not call an LLM.

Every search request selects one provider operation and carries the exact query intended for that
operation; query syntax is not assumed portable. OpenAlex receives the positional query. Semantic
Scholar relevance search uses `/paper/search` for plain-natural-language, relevance-ranked
exploration. Semantic Scholar bulk search uses `/paper/search/bulk` for Boolean/filter-oriented,
non-relevance-ranked retrieval. The CLI never guesses which S2 semantics a query intends.

```shell
uv run research-atlas-dry-run "urban heat mitigation systematic review" --limit 8
uv run research-atlas-dry-run "supply chain resilience" --limit 5 \
  --semantic-scholar-relevance "supply chain resilience systematic review"
uv run research-atlas-dry-run "museum conservation" --limit 5 \
  --semantic-scholar-bulk '"museum conservation" + (review | preservation)'
uv run research-atlas-dry-run "museum conservation methods" --output tmp/dry-run.json
uv run research-atlas-dry-run "supply chain resilience" --limit 5 \
  --semantic-scholar-relevance "supply chain resilience systematic review" \
  --diagnose-s2-requests
```

For complex native Semantic Scholar expressions on Windows PowerShell, pass the query through a
UTF-8 file so PowerShell and `uv run` never have to reinterpret its quotes or operators. The file's
contents are sent to Semantic Scholar exactly as written (including any trailing newline), so write
only the query text:

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
$bulkQueryPath = Join-Path $PWD "tmp\s2-bulk-query.txt"
$bulkQuery = '"intelligent tutoring systems" + ("meta analysis" | "systematic review")'
[IO.File]::WriteAllText($bulkQueryPath, $bulkQuery, [Text.UTF8Encoding]::new($false))
uv run research-atlas-dry-run "intelligent tutoring systems" --limit 1 `
  --semantic-scholar-bulk-file $bulkQueryPath
```

`--semantic-scholar-bulk QUERY` remains available for simple expressions and environments where
shell quoting is reliable. The inline and file forms are mutually exclusive.

OpenAlex and Semantic Scholar keys are optional for small calls. Copy `.env.example` to `.env` to
set `RESEARCH_ATLAS_OPENALEX_API_KEY` or
`RESEARCH_ATLAS_SEMANTIC_SCHOLAR_API_KEY`. Zotero access requires
`RESEARCH_ATLAS_ZOTERO_LIBRARY_ID`, `RESEARCH_ATLAS_ZOTERO_LIBRARY_TYPE` (`user` or
`group`), and an API key where the library requires one. The Zotero adapter is read-only and uses
`pyzotero`.

OpenAlex remains the primary provider and Semantic Scholar is optional. Provider operations are
isolated: a throttled relevance search is reported without discarding successful OpenAlex or S2
bulk results. Outcomes distinguish `openalex.search`, `semantic_scholar.relevance`, and
`semantic_scholar.bulk`, while records from both S2 operations retain canonical
`semantic_scholar` provenance. Discovery fails only when every requested operation fails. All
Semantic Scholar operations in one Python process share an async request coordinator that grants
actual request starts at least 1.1 seconds apart. A delayed waiter re-checks the monotonic clock and
cannot pass beside another overdue waiter. Pagination and every retry re-enter that coordinator.
The dry-run CLI also takes a fail-fast OS lock from system temporary storage whenever any S2
operation is requested, allowing only one S2-enabled Research Atlas dry run on the local machine at
a time. This lock is released on normal completion and exceptions and does not contain credential
material. Coordination across machines remains deferred.

S2 responses with `Retry-After` honor it. An S2 429 without that header waits 5 seconds before the
second attempt and 10 seconds before the third; 5xx and transport retries retain the generic short
0.5/1.0-second backoff. `--diagnose-s2-requests` prints one secret-safe line per physical S2 attempt
to stderr (operation, endpoint path, attempt, elapsed monotonic start, status, retry reason, and
delay) while JSON stdout remains clean. Authenticated live S2 canaries must run only from the
user's local checkout; Codex/cloud environments use mocks and fake clocks and must not run them.

OpenAlex sends its optional API key only as an `Authorization: Bearer` header. Its ordinary API
keeps provider-appropriate retry/backoff behavior and is not subjected to Semantic Scholar's 1.1
second throttle. Tighter endpoint-specific OpenAlex policies can be added if those endpoints are
adopted; usage and daily-budget telemetry are a future operational improvement.

Source IDs are UUID5 values over a canonical identity: DOI first, then PMID or arXiv, then provider
namespace plus provider record ID. DOI URLs, `doi:` prefixes, case, and whitespace are normalized.
Records merge only when these stable identities match; similar titles, authors, or years are kept
separate in v0.4. Provider provenance and external identifiers are combined deterministically.

## Development

Requires Python 3.14.7 and [uv](https://docs.astral.sh/uv/). Use uv to create and manage
the project `.venv`; uv reads `.python-version` and selects the intended Python patch release.

```shell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Research Run 001 has not been started. This dry run is explicitly not Run 001. The records schema
remains 0.3, and protocol and taxonomy versions are unchanged.
