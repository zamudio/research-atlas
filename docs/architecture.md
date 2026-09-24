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
SourceRecord -> StudyRecord -> MeasurementRecord / InterventionRecord
             -> FindingRecord -> EvidenceAssessment
             -> ArchitectureCandidate -> ProductImplication
```

`RecordProvenance` records how extracted or derived records were created and reviewed. It is
separate from provider provenance on bibliographic sources and uses extensible strings for
methods, tools, models, versions, and review states.

`ResearchRecords` is the centralized referential-integrity boundary. It rejects duplicate IDs and
dangling typed links before trusted dataclasses enter the application. Export counts are derived
from those validated collections and checked against the manifest when a bundle is assembled.

Protocols, taxonomies, research runs, construct registries, record schemas, and bundle manifests
carry independent versions because each can evolve at a different rate. Exports are immutable
artifacts whose content files may be verified with SHA-256 checksums.

Raw PDFs, large corpora, provider dumps, and temporary outputs stay in external or ignored storage.
No database, UI, agent framework, LLM pipeline, provider adapter, or consumer integration is part
of v0.2.
