# Research Atlas

Research Atlas is a reusable, provenance-first foundation for turning research into
reviewable product decisions. Version 0.4.2 adds conservative Semantic Scholar request pacing to the
v0.4 provider/ingestion foundation and its small
developer dry run while keeping the v0.3 records schema frozen.

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

The dry run discovers and normalizes publications with `--limit` applied per provider, so
`--limit 10` with two providers may return up to 20 sources before cross-provider deduplication. It
does not create `ResearchRun`, study, finding, evidence, architecture, or product records, and it
does not call an LLM.

`LiteratureQuery.query` is passed through as provider search syntax; precise phrase and Boolean
queries are recommended for evidence-focused searches. `LiteratureQuery.limit` is a per-provider
limit, so `--limit 3 --semantic-scholar` may return up to six unique normalized sources before
cross-provider deduplication. Broad semantic or exploratory discovery may be considered later but
is not part of v0.4.2.

```shell
uv run research-atlas-dry-run "urban heat mitigation systematic review" --limit 8
uv run research-atlas-dry-run "supply chain resilience" --limit 5 --semantic-scholar
uv run research-atlas-dry-run "museum conservation methods" --output tmp/dry-run.json
```

OpenAlex and Semantic Scholar keys are optional for small calls. Copy `.env.example` to `.env` to
set `RESEARCH_ATLAS_OPENALEX_API_KEY` or
`RESEARCH_ATLAS_SEMANTIC_SCHOLAR_API_KEY`. Zotero access requires
`RESEARCH_ATLAS_ZOTERO_LIBRARY_ID`, `RESEARCH_ATLAS_ZOTERO_LIBRARY_TYPE` (`user` or
`group`), and an API key where the library requires one. The Zotero adapter is read-only and uses
`pyzotero`.

OpenAlex remains the primary provider and Semantic Scholar is an optional secondary provider.
Provider searches are isolated: a throttled or unavailable secondary provider is reported in the
dry-run output without discarding successful OpenAlex results. Discovery fails only when every
configured provider fails. All requests made by one Semantic Scholar adapter instance, including
retries and future endpoint methods, share an async client-side limiter with at least 1.1 seconds
between request starts. This conservatively paces authenticated traffic below the approved
1 request/second cumulative limit without applying Semantic Scholar's limit to OpenAlex.

Source IDs are UUID5 values over a canonical identity: DOI first, then PMID or arXiv, then provider
namespace plus provider record ID. DOI URLs, `doi:` prefixes, case, and whitespace are normalized.
Records merge only when these stable identities match; similar titles, authors, or years are kept
separate in v0.4. Provider provenance and external identifiers are combined deterministically.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```shell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Research Run 001 has not been started. This dry run is explicitly not Run 001. The records schema
remains 0.3, and protocol and taxonomy versions are unchanged.
