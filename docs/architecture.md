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

The domain does not import provider SDKs or consumer code. Provider identifiers are provenance,
not primary identity. Study UUIDs and linked record IDs keep decisions traceable through evidence
and constructs to sources.

Protocols, taxonomies, research runs, construct registries, record schemas, and bundle manifests
carry independent versions because each can evolve at a different rate. Exports are immutable
artifacts whose content files may be verified with SHA-256 checksums.

Raw PDFs, large corpora, provider dumps, and temporary outputs stay in external or ignored storage.
No database, UI, LLM pipeline, provider adapter, or consumer integration is part of v0.1.
