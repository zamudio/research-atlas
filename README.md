# Research Atlas

Research Atlas 0.5.0 is reusable, provenance-first evidence infrastructure. It supports one
project's research workflow, a shared local evidence ecosystem used by multiple agents or
applications, and eventual hosted API/SaaS deployment without putting provider or consumer
semantics into the epistemic core.

The records schema is 0.4. This is an intentional breaking migration from records schema 0.3.

## Four separate concerns

Research Atlas keeps four kinds of truth distinct:

1. A validated `RunDefinition` says what a project intends to do. Its deterministic SHA-256
   fingerprint identifies the complete approved plan.
2. `ResearchRun`, `SearchExecution`, `SourceDiscovery`, and append-only `ScreeningDecision`
   records say what actually happened.
3. Sources, studies, findings, constructs, and `EvidenceAssessment` records say what the research
   supports and where uncertainty remains.
4. Optional `ApplicationCandidate` and `DecisionImplication` records say how one consumer may use
   assessed evidence. They reference evidence and never mutate or rewrite it.

A scholarly project needs no translation profile or translation records. Consumer-specific
destinations and constraints belong in an optional `TranslationProfile`, not `ProjectProfile` or
`ConstructRecord`.

## Boundaries

Core code is consumer-neutral and provider-neutral. `project_id` and `run_id` are opaque
identities, never behavior switches. Exact queries, screening reason codes, taxonomies,
destinations, and project vocabulary remain project/run data.

OpenAlex and Semantic Scholar are literature-source adapters. Zotero is a reference-library
adapter. Crossref is intentionally not integrated in 0.5, but can be added as another
`LiteratureSource` operation without changing domain records or the discovery use case. Provider
metadata provenance (`SourceProvenance`) remains distinct from research-search provenance
(`SourceDiscovery`).

Static checksummed bundles remain a supported portable integration mode, but not the only one.
Applications may also embed the package, implement `ResearchWorkStore` for resumable local work,
or place the same application/domain contracts behind an API. Storage technology does not enter
domain models.

## Lifecycle

```text
ProjectProfile + optional TranslationProfile
                    |
                    v
             RunDefinition
                    |
          fingerprinted approval
                    v
              ResearchRun
         /          |           \
SearchExecution  SourceDiscovery  ScreeningDecision
                    |
                    v
 Source -> Study -> Finding -> EvidenceAssessment
                                  |
                           optional boundary
                                  v
               ApplicationCandidate -> DecisionImplication
```

Search specs have stable `search_spec_id` values. Provider `operation_id` identifies provider
semantics and is not a research-search identity; one discovery batch may therefore issue multiple
requests to the same operation. Each logical execution records exact query text, parameters,
timing, status, result count, and safe failure metadata. Physical HTTP pages, attempts, and retries
remain adapter telemetry rather than epistemic records.

Screening is append-only. A later decision may reference `supersedes_decision_id`; current state
is derived from decisions that have not been superseded. Study-level decisions must identify a
study belonging to the selected source.

Protocol references are extensible `(protocol_id, version, phase)` records. Extraction, screening,
evidence assessment, and translation protocols can evolve independently. Epistemic-only work is
not forced to claim a translation protocol.

## Repository map

- `src/research_atlas/domain`: frozen trusted dataclasses for evidence and execution records.
- `src/research_atlas/schemas`: Pydantic configuration and serialization boundaries.
- `src/research_atlas/application`: provider-neutral orchestration, persistence ports, and export.
- `src/research_atlas/infrastructure/providers`: OpenAlex, Semantic Scholar, and Zotero adapters.
- `protocol`: independently versioned generic research protocols.
- `projects`: project-owned profiles, optional translation profiles, taxonomies, and run plans.

## Provider dry run

The dry run discovers and normalizes source metadata only. It does not create a `ResearchRun`,
does not start Run 001, and does not invoke an LLM.

```shell
uv run research-atlas-dry-run "urban heat mitigation systematic review" --limit 8
uv run research-atlas-dry-run "supply chain resilience" --limit 5 \
  --semantic-scholar-relevance "supply chain resilience systematic review"
uv run research-atlas-dry-run "museum conservation" --limit 5 \
  --semantic-scholar-bulk '"museum conservation" + (review | preservation)'
```

Every request explicitly selects an operation and retains exact query text. Query syntax is never
assumed portable. Partial provider success is preserved; discovery fails only if all requested
operations fail. Stable scholarly identity uses DOI, then PMID or arXiv, then provider namespace
and record ID. Similar titles are not fuzzily merged.

Semantic Scholar relevance and bulk operations retain their distinct endpoint semantics. All S2
requests, pagination, and retries share the existing 1.1-second in-process coordinator. The CLI
also retains same-machine single ownership for S2-enabled dry runs. `Retry-After`, safe retry
backoff, secret-safe diagnostics, and the ban on authenticated live canaries in Codex/cloud
environments remain unchanged. OpenAlex keeps its provider-appropriate retry behavior and sends an
optional key only in the authorization header. Zotero remains read-only.

## Development

Requires Python 3.14.7 and [uv](https://docs.astral.sh/uv/).

```shell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

`projects/ai-tutor/runs/learning-foundations-001.yaml` is still `planned`. Its stable search
intents validate, but exact execution-ready queries have not been approved. Research Run 001 has
not started and this migration makes no live provider calls.
