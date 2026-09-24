# Architecture

Research Workbench uses a small ports-and-domain boundary.

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

Literature discovery is async because OpenAlex and Semantic Scholar are independent network calls;
the application service can execute them concurrently while exposing one consistent port. The
read-only Zotero reference-library port remains synchronous because `pyzotero` is synchronous.
Raw response types are contained in adapters and never enter application or domain contracts.

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
  -> ArchitectureCandidate
  -> ProductImplication
```

`EvidenceAssessment` evaluates an explicit human-readable claim or body of evidence. It links the
supporting, contradictory, and null findings and may link zero or more relevant constructs; it is
not owned by one construct. Architecture candidates are justified primarily by linked evidence and
may also link constructs when useful. Product-decision records do not duplicate study links because
the study and source path is derivable through evidence and findings.

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
