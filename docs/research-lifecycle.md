# Research lifecycle

## 1. Define and approve

`ProjectProfile` describes domain-neutral project goals and constraints. An optional
`EvidenceApplicationProfile` describes a consumer, allowed destinations, and application
constraints. Neither is execution state.

A `RunDefinition` fixes questions, scope, logical search specifications, screening plans, stopping
rules, protocol and taxonomy references, and expected outputs. Planned definitions may omit exact
queries. Planned SearchSpec identities may evolve while exact operation-specific searches are
formulated; they become stable at approval. An approved definition requires every `SearchSpec` to
be execution-ready with a non-blank provider, operation, exact query, and an explicit positive
requested limit. Query contents are preserved exactly.

## 2. Execute

`ResearchRun` identifies the approved definition through its reference, schema version, and
fingerprint. `SearchExecution` records each logical approved search once, including exact query,
provider-neutral `(name, value)` parameters, requested limit, timing, outcome, result count, and
safe failure metadata. Provider requests, pages, and retries are not copied into this record.

`SourceDiscovery` connects a successful search execution to a normalized `SourceRecord`. A source
may be found by multiple searches or providers. `discovery_record_id`, when present, belongs to the
discovery system. `SourceProvenance` separately records where normalized source metadata came from;
it need not name the discovery provider or share its record ID.

## 3. Screen and assess evidence

`ScreeningDecision` is append-only. A correction creates a new decision linked by
`supersedes_decision_id`; current state is derived rather than overwritten. Study-level decisions
must point to a study belonging to the selected source. At export, each decision's stage and reason
codes must be declared by the approved screening plan.

Evidence proceeds from source to study, measurements or interventions, findings, and finally an
`EvidenceAssessment`. Assessments keep contradictory and null findings, uncertainty, measurement
limits, and generalizability visible. Revised assessments use `supersedes_evidence_id`; links must
remain acyclic and within the same creating run, while semantic equivalence remains a review
responsibility.

## 4. Apply evidence when appropriate

Evidence application is optional and downstream. `ApplicationCandidate` and
`DecisionImplication` retain links to the supporting assessments and their own provenance. They may
interpret evidence for a consumer decision but cannot modify, relabel, or replace an
`EvidenceAssessment`.

## 5. Export a portable snapshot

An `ExportBundle` contains a manifest, records, and each contributing run's validated definition
snapshot. Bundle schema and records schema are identified independently. Validation recomputes
fingerprints and compares every execution to its approved search spec, including exact generic
parameters and requested limit. A serialized and restored bundle therefore retains both intent
and execution integrity.
