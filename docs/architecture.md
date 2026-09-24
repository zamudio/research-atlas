# Architecture

Research Atlas uses a small ports-and-domain boundary.

## Reusable core boundary

The package is reusable infrastructure, not an AI Tutor or learning-science application. Core
owns generic records, validation, provenance, discovery ports, provider adapters, synthesis
contracts, and export mechanics. Projects own the meaning and content supplied to those
contracts.

`project_id` is opaque project data and a namespace. It is compared for export consistency but
must never select code paths, queries, schemas, taxonomies, or destinations. `run_id` is generic
run identity: the v0.3 boundary requires it to be unique among the research runs in one validated
`ResearchRecords` collection, and provenance and manifests reference that exact value. Run IDs
are not scoped or interpreted by core behavior.

The following belong to project profiles or run definitions:

- exact search queries and research questions;
- inclusion and exclusion rules, scope, stopping rules, and evidence priorities;
- project vocabulary and the versioned taxonomy selected by the run; and
- product-specific destinations and translation constraints.

Core destination fields remain strings. For example, an AI Tutor project may supply `state`,
`policy`, `curriculum`, `telemetry`, or `ux`; another project may supply entirely different
destinations without a core change. Generic `ArchitectureCandidate` and `ProductImplication`
records may reference those project-supplied destinations.

Evidence synthesis and product translation are separate stages. Translation may reference an
existing `EvidenceAssessment` but must not mutate, relabel, or rewrite it. Architecture candidates
and product implications are optional: an epistemic run can stop after synthesis. Adding a new
project therefore requires project/run data, not edits to `src/research_atlas`.

Project-owned files live under `projects/`, outside the package import boundary. Core does not
import them.

```text
external tools/providers
        |
infrastructure adapters (OpenAlex / Semantic Scholar / Zotero)
        |
application-owned ports + discovery/identity service
        |
Pydantic import boundaries
        |
trusted frozen domain dataclasses + versioned protocol
        |
Pydantic static export manifest and normalized records
        |
consumer-owned import process (no runtime package dependency)
```

The domain does not import provider SDKs or consumer code. Provider identifiers remain source
provenance, not primary identity. Application ports discover or retrieve `SourceRecord` objects;
one source may report multiple `StudyRecord` objects. Study findings are captured independently
before cross-study synthesis.

Literature discovery is async because provider operations are independent network calls; the
application service executes explicit search requests concurrently through one consistent port.
Each request pairs one selected operation with its exact query, so provider query syntax is never
assumed portable. Each outcome reports both canonical provider and operation, partial success
preserves available results, and discovery fails only when all requested operations fail. The query
limit applies to each operation rather than globally; all unique results remain after exact-identity
deduplication. The
read-only Zotero reference-library port remains synchronous because `pyzotero` is synchronous.
Raw response types are contained in adapters and never enter application or domain contracts.

Semantic Scholar relevance search is a plain-natural-language, relevance-ranked operation using
`/paper/search`. Boolean/filter-oriented retrieval is a separate, non-relevance-ranked bulk
operation using `/paper/search/bulk` and its continuation token. Both retain canonical
`semantic_scholar` source provenance while their discovery outcomes use distinct operation labels.
Exact query strings and operation choices remain project/run data. A relevance failure does not
invalidate successful bulk or other-provider results.

Semantic Scholar's credential-wide traffic policy is represented by one process-wide in-process
coordinator shared by every S2 operation and endpoint. It atomically reserves monotonic
request-start slots at least 1.1 seconds apart across all default adapter instances; pagination and
retries pass through the same boundary. It does not coordinate across OS processes or machines,
and operations therefore allow only one active Semantic Scholar-using process per key. Distributed
coordination is intentionally deferred.

OpenAlex authentication uses an `Authorization: Bearer` header, never a query parameter. OpenAlex
retains provider-appropriate retry/backoff without an artificial 1.1-second global throttle because
its ordinary and specialized endpoints have different policies. Endpoint-specific coordination and
usage/budget telemetry can be added later where required.

Canonical scholarly identity is DOI, then PMID or arXiv, then provider namespace plus provider
record ID. Internal source UUIDs are UUID5 values over that identity. Deduplication merges only an
exact normalized stable identity and deterministically unions external identifiers and provider
provenance. It intentionally does not use fuzzy title/author/year matching, so uncertain records
remain separate for human review.

```text
SourceRecord
  -> StudyRecord
  -> MeasurementRecord / InterventionRecord
  -> FindingRecord
  -> EvidenceAssessment
  -> optional, separate product translation
       -> ArchitectureCandidate
       -> ProductImplication
```

`EvidenceAssessment` evaluates an explicit human-readable claim or body of evidence. It links the
supporting, contradictory, and null findings and may link zero or more relevant constructs; it is
not owned by one construct. Architecture candidates are justified primarily by linked evidence and
may also link constructs when useful. Product-decision records do not duplicate study links because
the study and source path is derivable through evidence and findings. Product-decision records
reference assessments; they do not replace or modify them.

`RecordProvenance` is required on extracted or derived records and records how they were created
and reviewed, including the creating research run. It is separate from provider provenance on
bibliographic sources and uses extensible strings for methods, tools, models, versions, and review
states. The centralized boundary rejects provenance that names a run absent from the record set.

`ResearchRecords` is the centralized referential-integrity boundary. It rejects duplicate IDs and
dangling typed links before trusted dataclasses enter the application. Export counts are derived
from those validated collections and checked against the manifest when a bundle is assembled.
Every contributing run named by an export manifest must be present in the bundled records and must
match the manifest's project ID, protocol versions, and taxonomy version.

Extraction, evidence-assessment, and architecture-promotion protocol components have explicit,
independent versions in research runs and export manifests. Taxonomies, construct registries,
record schemas, and bundle manifests remain separately versioned because each can evolve at a
different rate. Exports are immutable artifacts whose content files may be verified with SHA-256
checksums.

Raw PDFs, large corpora, provider dumps, and temporary outputs stay in external or ignored storage.
The v0.4 dry-run command emits only normalized source metadata to stdout or an ignored `tmp/` or
`exports/` path. It creates no research-run or downstream research records and invokes no LLM.
Elicit remains a manual tool on the free/basic tier; any later export/API adapter can enter through
the existing ports, with no scraping or browser automation around service limits. Research Run 001
has not started. Records schema 0.3 and all protocol and taxonomy versions remain frozen.
