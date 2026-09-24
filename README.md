# Research Workbench

Research Workbench is a reusable, provenance-first foundation for turning research into
reviewable product decisions. Version 0.3.1 completes the pre-integration export-integrity pass;
it does not perform literature searches or connect to providers.

## What it is

- A normalized internal representation for bibliographic sources, studies, constructs,
  measurements, interventions, findings, evidence assessments, and product implications.
- A versioned protocol for extracting, assessing, and promoting research into product guidance.
- A producer of static, versioned export bundles that consumer projects can import without a
  runtime dependency on this package.

## What it is not

It is not a paper database replacement, an Elicit clone, a scientific authority, a web UI, an
agent framework, or a claim that qualitative review can be reduced to one universal score.

Zotero, Elicit, OpenAlex, Semantic Scholar, ResearchRabbit, Litmaps, and similar tools are useful
infrastructure. Future adapters may acquire records through them, but provider-specific models
must stop at application-owned ports. The normalized records and documented review decisions in
this repository are the internal source of truth.

Consumer projects such as AI Tutor receive curated exports. They do not import or run Research
Workbench in production.

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

- `src/research_workbench/domain`: trusted internal dataclasses.
- `src/research_workbench/schemas`: validated import, configuration, and record boundaries.
- `src/research_workbench/application/ports`: provider-neutral acquisition interfaces.
- `src/research_workbench/application/export`: static bundle contracts and checksums.
- `protocol`: independently versioned taxonomy, extraction, evidence, and promotion guidance.
- `templates`: example project profiles; these do not start a research run.

Raw PDFs, corpora, provider dumps, and generated exports are intentionally ignored by Git.

## Development

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```shell
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

Research Run 001 has not been started. The core schema is intended to remain frozen through Run
001 unless real data demonstrates a necessary change. Provider adapters remain outside the v0.3
hardening scope.
