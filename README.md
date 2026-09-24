# Research Atlas

Research Atlas is a reusable, provenance-first foundation for turning research into
reviewable product decisions. Version 0.4 adds a provider/ingestion foundation and a small
developer dry run while keeping the v0.3 records schema frozen.

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

Consumer projects such as AI Tutor receive curated exports. They do not import or run Research
Atlas in production.

## Lifecycle

1. Define a consumer-aware `ProjectProfile`.
2. Conduct versioned research runs using an approved protocol and taxonomy.
3. Normalize publications into source records, then separate studies or analyses.
4. Extract studies, constructs, measurements, interventions, and study-level findings with required
   process provenance tied to the creating research run.
5. Synthesize findings into claim-centered evidence assessments, optionally linking relevant
   constructs.
6. Review architecture candidates and product implications.
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
- `protocol`: independently versioned taxonomy, extraction, evidence, and promotion guidance.
- `templates`: example project profiles; these do not start a research run.

Raw PDFs, corpora, provider dumps, and generated exports are intentionally ignored by Git.

## Provider dry run

The dry run discovers and normalizes 1–10 publications. It does not create `ResearchRun`, study,
finding, evidence, architecture, or product records, and it does not call an LLM.

```shell
uv run research-atlas-dry-run "formative feedback intelligent tutoring" --limit 8
uv run research-atlas-dry-run "formative feedback" --limit 5 --semantic-scholar
uv run research-atlas-dry-run "formative feedback" --output tmp/dry-run.json
```

OpenAlex and Semantic Scholar keys are optional for small calls. Copy `.env.example` to `.env` to
set `RESEARCH_ATLAS_OPENALEX_API_KEY` or
`RESEARCH_ATLAS_SEMANTIC_SCHOLAR_API_KEY`. Zotero access requires
`RESEARCH_ATLAS_ZOTERO_LIBRARY_ID`, `RESEARCH_ATLAS_ZOTERO_LIBRARY_TYPE` (`user` or
`group`), and an API key where the library requires one. The Zotero adapter is read-only and uses
`pyzotero`.

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
