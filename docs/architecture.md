# Architecture

Research Atlas separates project configuration, research execution, epistemic records, optional
evidence application, and infrastructure. Domain records import no provider SDK, storage system,
consumer package, or agent framework. IDs and destination strings are data, never behavior
switches.

## Boundaries

```text
project-owned configuration                 portable output
ProjectProfile                              ExportBundle
EvidenceApplicationProfile (optional)       |- RunDefinitionSnapshot(s)
RunDefinition                               |- ResearchRecords
taxonomy and protocols                      `- manifest
          |                                          ^
          v                                          |
application services -> immutable domain records ----+
          ^
          |
provider and persistence adapters
```

`RunDefinition` owns approved intent. `ResearchRecords` owns executed and epistemic facts; it does
not own project configuration. `ExportBundle` is the boundary that joins both for portability and
therefore validates the relationship between them.

## Definition and execution integrity

A run definition contains question and search-spec IDs, scope, screening and stopping plans,
protocol and taxonomy references, evidence strategy, outputs, and limitations. Planned
definitions may change those identities as exact searches are designed; they become stable when a
definition is approved. Canonical JSON over the complete validated model produces a deterministic
SHA-256 fingerprint.

A `ResearchRun` stores the definition reference, schema version, and fingerprint it executed.
Every contributing run in an export has exactly one `RunDefinitionSnapshot`. Bundle validation
requires an approved definition and exact agreement on run ID, project, reference, schema version,
fingerprint, protocol references, and taxonomy reference/version.

Each `SearchExecution` is one logical execution. The bundle verifies that its `search_spec_id`
exists in the corresponding definition and that provider, operation, exact query, generic
parameters, and requested limit match the approved `SearchSpec`. Exact query content is compared
without normalization. Physical HTTP attempts, pages, throttling, and retries remain operational
telemetry, not epistemic records.

## Evidence and optional application

```text
SourceRecord -> StudyRecord -> MeasurementRecord / InterventionRecord
             -> FindingRecord -> EvidenceAssessment
                                      |
                               optional boundary
                                      v
                    ApplicationCandidate -> DecisionImplication
```

`FindingRecord` captures what a study reported. `EvidenceAssessment` captures a transparent
cross-finding assessment. `ConstructRecord` contains epistemic definitions, observables,
moderators, timescales, and inference risks—not consumer architecture requirements.

Evidence application is optional. Destinations and constraints come from an optional
`EvidenceApplicationProfile`. Application records may reference evidence and constructs but cannot
rewrite an `EvidenceAssessment`. A scholarly project remains valid without an application profile
or application records.

## Referential integrity and portability

`ResearchRecords` schema 0.5 rejects duplicate IDs, dangling references, inconsistent discovery
and screening chains, and invalid append-only screening/evidence supersession. A
`SourceDiscovery` must agree with its successful `SearchExecution` and run. It records the
discovery mechanism and may legitimately differ from `SourceProvenance`, which records the origin
of normalized bibliographic metadata.

`ProtocolReference(protocol_id, version, phase)` keeps protocols independently evolvable.
`RecordProvenance.creation_method` applies across import, extraction, synthesis, screening, review,
and application. Bundle schema 0.1 independently describes the portable manifest + run-definition
snapshots + records shape, while the manifest identifies the records schema separately. Static
bundles are immutable portable snapshots; direct package use, local persistence behind
`ResearchWorkStore`, and a future API remain compatible delivery modes.

## Deliberate limits

Version 0.6.0 includes an experimental Crossref feasibility adapter, but does not adopt it as a
permanent secondary provider or authorize Run 001 execution. It adds no billing, authentication,
tenancy, distributed jobs, PostgreSQL, fuzzy matching, universal evidence ontology, or
agent-framework coupling. Run 001 is planned and unexecuted.
