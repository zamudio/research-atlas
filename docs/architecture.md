# Architecture

Research Workbench uses a small ports-and-domain boundary.

```text
external tools/providers
        |
application-owned ports (future adapters)
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
No database, UI, agent framework, LLM pipeline, provider adapter, or consumer integration is part
of v0.3. Research Run 001 has not started.
