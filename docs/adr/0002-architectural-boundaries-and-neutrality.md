# ADR 0002: Architectural boundaries and neutrality

## Status

Accepted. This ADR records an established boundary; it is not a new proposal.

## Context

Research Atlas is reusable, global evidence infrastructure. AI Tutor is one project and possible
consumer, not the owner of Research Atlas concepts. The architecture must keep research intent,
what actually happened, the evidence produced, and later use of that evidence distinguishable.

## Decision

Research Atlas uses this conceptual separation:

```text
Definition → Execution → Evidence → Application
```

- **Definition** describes intended research: questions, scope, search specifications, screening
  and stopping plans, protocols, taxonomy, and expected outputs.
- **Execution** records what actually ran, including research runs, search executions, discoveries,
  and screening decisions.
- **Evidence** records sources, studies, findings, constructs, assessments, and their provenance.
- **Application** is an optional downstream interpretation of assessed evidence for a consumer. It
  must not rewrite the evidence.

The epistemic and domain core remains independent of:

- individual scholarly providers;
- persistence technology;
- AI Tutor;
- LLM or agent frameworks; and
- downstream consumer applications.

Provider and persistence implementations belong behind ports and application boundaries. Project
configuration and consumer-specific application profiles remain outside the reusable domain core.
Identifiers or destination strings are data, not switches that introduce consumer behavior into
core records.

The architectural test is:

> If AI Tutor disappeared tomorrow, Research Atlas core abstractions should still make sense.

## Consequences

Research Atlas may support AI Tutor without becoming its subsystem. Other scholarly projects and
consumers can use the same definitions, execution history, evidence records, and export contracts.
Provider changes, persistence work, and agent orchestration must not alter the meaning of core
epistemic records.
