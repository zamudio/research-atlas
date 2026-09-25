# Research Atlas

Research Atlas is reusable infrastructure for evidence-backed research. It keeps what was
planned, what actually ran, what the evidence supports, and how evidence is applied separate and
traceable. It is designed for humans, agents, and products without binding the evidence model to
one provider or downstream application.

## Four concerns

1. **Definition:** a validated, fingerprinted `RunDefinition` states approved intent.
2. **Execution:** immutable run, search, discovery, and screening records state what happened.
3. **Evidence:** sources, studies, findings, constructs, and assessments state what is supported
   and where uncertainty remains.
4. **Application:** optional candidates and implications describe how assessed evidence may inform
   a consumer without rewriting the evidence.

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
```

## Developer quickstart

Requires Python 3.14.7 and [uv](https://docs.astral.sh/uv/).

```shell
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The metadata-only dry run is documented in the [CLI guide](docs/cli.md). It does not create a
research run or invoke an LLM. The first real research run remains planned and unexecuted.

- [Documentation home](docs/index.md)
- [Architecture and boundaries](docs/architecture.md)
- [Research lifecycle](docs/research-lifecycle.md)
- [Providers and safety](docs/providers.md)
- [CLI guide](docs/cli.md)
