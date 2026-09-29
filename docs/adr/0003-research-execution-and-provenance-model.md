# ADR 0003: Research execution and provenance model

## Status

Superseded by the [lean v1 architecture intervention](../architecture.md), following the
independent architecture audit. The original decision below is retained as historical rationale,
not a current implementation requirement. Execution/provenance distinctions survive, while
formal approval, contract coupling, and durable contributor identity do not.

## Context

Reproducible research requires intended work, actual executions, discovered sources, and source
metadata origins to remain distinguishable. A metadata-only discovery report also needs temporary
coordinates before durable execution records exist, without turning those coordinates into entity
identity.

## Decision

- `RunDefinition` describes intended research. The validated model is frozen; an export's
  `RunDefinitionSnapshot` captures that immutable definition together with its project-owned
  reference.
- `ResearchRun` represents an actual execution of a validated, approved definition. It records the
  definition reference, schema version, and fingerprint that it executed.
- `SearchExecution` represents an actual logical execution of an intended `SearchSpec`. It retains
  the intended `search_spec_id` and the exact provider operation inputs that actually ran.
- `SourceDiscovery` records that a `Source` (represented by `SourceRecord` in the current model) was
  discovered by a particular successful `SearchExecution` in a research run.
- `Source` is the Atlas-owned representation of a publication or other research-bearing work. Its
  identity is governed by [ADR 0001](0001-durable-source-identity.md), not by discovery coordinates
  or provider metadata.

Discovery provenance and metadata provenance are separate concepts. `SourceDiscovery` says how a
source entered a run. `SourceProvenance` says where normalized bibliographic metadata came from.
Their providers and provider-native record identifiers may differ.

Application discovery currently uses `search_index` as a temporary, zero-based in-memory coordinate
into the ordered requested searches. Before persistence, that coordinate must be resolved to the
actual durable `search_execution_id` for the corresponding execution. `search_index` must never be
stored or treated as a durable foreign key.

`result_position` is the provider-returned one-based rank of a result within that requested search.
It is discovery context, not Source identity.

`ExportBundle` requires exact run membership: the manifest's `contributing_run_ids` and
`ResearchRecords.research_runs` must contain the same run IDs. Run-definition snapshots additionally
match the manifest run IDs in order and are validated against the runs and their search executions.

## Consequences

Planned definitions can be reviewed without claiming execution. Multiple search executions can
implement intended searches, and multiple discoveries can connect a source to the executions that
found it. Bibliographic metadata can be normalized from a provider other than the discovery
provider without losing either provenance chain.

This decision defines conceptual identities and referential requirements. It does not choose
PostgreSQL tables, keys, indexes, repository layout, or transaction boundaries.
