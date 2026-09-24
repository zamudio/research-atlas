# Architecture

Research Atlas is a small ports-and-domain system for evidence work across three deployment
scopes: project-specific research, a shared local ecosystem serving multiple agents/products, and
eventual hosted/API applications. The same domain and application contracts should work in every
scope.

## Dependency direction

```text
project-owned YAML
  ProjectProfile / TranslationProfile / RunDefinition / taxonomy
                              |
                              v
application composition and ports <--- future local or hosted persistence
  discovery / identity / export      (`ResearchWorkStore`)
             |                                   |
             v                                   v
trusted frozen domain records <--- Pydantic validation boundaries
             ^
             |
infrastructure adapters
  OpenAlex / Semantic Scholar / future Crossref / Zotero
```

Domain records import no provider SDK, storage type, consumer package, or agent framework.
Infrastructure implements application-owned ports. Core never branches on a project ID,
destination string, or provider record shape.

## Definition, execution, evidence, translation

`RunDefinition` is a project-owned, validated plan. It contains stable research-question IDs,
stable search-spec IDs, scope, screening and stopping plans, protocol/taxonomy references,
evidence strategy, outputs, and limitations. It contains no start timestamps, result counts,
included studies, or other claims about work performed. Canonical JSON over the complete validated
model produces a deterministic SHA-256 fingerprint.

`ResearchRun` is a lean execution instance. It proves which definition was used through the
definition reference, schema version, and fingerprint. It carries only run identity, execution
status/timing, and the protocol/taxonomy metadata needed to verify a portable record set.

`SearchExecution` represents one logical execution of one `search_spec_id`. Its `operation_id`
names provider semantics, so operation IDs may repeat across requests. Exact query text is retained
without normalization. Parameters, requested limits, timing, logical status, result count, and safe
errors make success and failure reproducible. HTTP attempts, pages, throttling, and retries stay in
infrastructure telemetry.

`SourceDiscovery` links a search execution to a normalized source. Many searches, providers, or
runs may discover the same source. This does not replace `SourceProvenance`, which says where
bibliographic metadata originated.

`ScreeningDecision` is append-only and may address a publication or one study within it. A small
decision vocabulary keeps cross-project processing predictable while reason codes stay extensible
project/run strings. Supersession links preserve history and current state is derived.

Evidence records follow the deliberately scholarly model:

```text
SourceRecord
  -> StudyRecord
  -> MeasurementRecord / InterventionRecord
  -> FindingRecord
  -> EvidenceAssessment
```

The 0.5 migration does not generalize this into a universal non-scholarly evidence ontology.
`FindingRecord` captures what a study reported; `EvidenceAssessment` captures Research Atlas's
transparent cross-finding assessment. `ConstructRecord` contains epistemic material such as
definitions, literature-derived observables, moderators, timescales, and inference risks—not
consumer architecture requirements.

Translation is optional and downstream:

```text
EvidenceAssessment
  -> ApplicationCandidate
  -> DecisionImplication
```

Translation records may link relevant constructs, but they cannot modify an evidence assessment.
Destinations and constraints come from an optional `TranslationProfile`. A project doing only
scholarly synthesis remains valid without one.

## Validation and portability

`ResearchRecords` schema 0.4 is the centralized integrity boundary. It rejects duplicate IDs and
dangling run, search, source, study, finding, evidence, translation, provenance, and supersession
links. It also enforces search-discovery run consistency and study/source consistency for
screening. Derived state is not copied into `ResearchRun`.

`RecordProvenance.creation_method` applies equally to import, extraction, synthesis, screening,
review, and translation. Tool/model/reviewer/version/review metadata remain optional and
provider-neutral.

`ProtocolReference(protocol_id, version, phase)` allows protocol components to evolve or be added
without a records-schema change. An epistemic run can cite extraction, screening, and assessment
protocols without claiming a translation protocol.

Export counts cover every records-schema collection. Bundle construction verifies counts,
contributing runs, project identity, protocol references, taxonomy reference/version, and content
checksums. Static bundles are immutable portable snapshots. They coexist with direct package use,
local persistence behind `ResearchWorkStore`, and future API delivery.

## Provider and identity boundaries

`LiteratureSource` accepts exact provider-appropriate query text and returns normalized
`SourceRecord` objects. OpenAlex and Semantic Scholar are current adapters; Crossref can be added
as another adapter/operation without changing this port. The remaining Crossref work is adapter
implementation and mapping its response/retry semantics—not a core-contract blocker.

Canonical identity is DOI, then PMID or arXiv, then provider namespace plus record ID. Only exact
normalized stable identities merge. Provider provenance is combined deterministically, while
uncertain fuzzy matches remain separate for review.

Semantic Scholar coordination, retry/backoff, diagnostics, and same-machine ownership remain
infrastructure concerns and are unchanged by the records migration. Zotero is a separate read-only
reference-library port.

## Deliberate limits

Version 0.5 adds no billing, authentication, tenancy, distributed jobs, PostgreSQL, fuzzy matching,
universal evidence ontology, or agent-framework coupling. Run 001 remains planned and unexecuted;
its definition contains search intents but no invented exact queries.
