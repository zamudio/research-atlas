# Research Atlas

Research Atlas 0.5.1 is reusable, provenance-first infrastructure for planning research,
recording what was executed, assessing evidence, and optionally applying that evidence. Core
records remain provider-neutral and consumer-neutral. The records schema remains 0.4.

## Four concerns

1. **Definition:** a validated, fingerprinted `RunDefinition` states approved intent.
2. **Execution:** `ResearchRun`, `SearchExecution`, `SourceDiscovery`, and append-only
   `ScreeningDecision` records state what happened.
3. **Evidence:** sources, studies, findings, constructs, and `EvidenceAssessment` state what the
   research supports and where uncertainty remains.
4. **Application:** optional `ApplicationCandidate` and `DecisionImplication` records describe how
   assessed evidence may inform a consumer. They never mutate an evidence assessment.

```text
ProjectProfile + optional EvidenceApplicationProfile
                         |
                  RunDefinition
                         |
                    ResearchRun
                         |
       SearchExecution -> SourceDiscovery -> Screening
                         |
       Source -> Study -> Finding -> EvidenceAssessment
                                             |
                                      optional application
                                             |
                         ApplicationCandidate -> DecisionImplication
```

Portable bundles include the validated run-definition snapshots used by their contributing runs.
Bundle validation checks fingerprints and ensures each logical search exactly matches its approved
provider, operation, query, parameters, and requested limit.

## Quickstart

Requires Python 3.14.7 and [uv](https://docs.astral.sh/uv/).

```shell
uv sync
uv run research-atlas-dry-run "urban heat mitigation systematic review" --limit 8
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The dry run discovers metadata only. It does not create a `ResearchRun`, start Run 001, or invoke
an LLM. See the [CLI guide](docs/cli.md) for Semantic Scholar operations, safe PowerShell bulk-query
input, and request diagnostics.

## Status and documentation

Run 001 remains `planned` and has no invented execution-ready queries. Crossref is not integrated;
its future work is confined to an adapter and provider-specific response/retry mapping.

- [Documentation home](docs/index.md)
- [Architecture and boundaries](docs/architecture.md)
- [Research lifecycle](docs/research-lifecycle.md)
- [Providers and safety](docs/providers.md)
- [CLI guide](docs/cli.md)
