# Research Atlas documentation

Research Atlas is provenance-first evidence infrastructure with explicit boundaries between
research intent, execution, evidence, and optional evidence application.

## Guides

- [Architecture](architecture.md) explains durable component and ownership boundaries.
- [Architecture decisions](adr/README.md) records accepted durable decisions and their status.
- [Naming and identifier glossary](architecture/naming-and-identifiers.md) defines canonical terms.
- [Research lifecycle](research-lifecycle.md) follows a run from approved definition through
  evidence and optional application.
- [Providers](providers.md) explains adapter roles, source identity, and operational safety.
- [CLI](cli.md) documents dry-run usage, complex Semantic Scholar queries, and diagnostics.

For installation and a compact project overview, start with the [repository README](../README.md).

## Current contracts

- Package version: 0.6.0
- Run-definition schema: 0.2
- Records schema: 0.6
- Export-bundle schema: 0.1
- Implemented OpenAlex operations: lexical works search and semantic search
- Implemented Semantic Scholar operations: optional relevance and bulk search
- Implemented Crossref operation: experimental bibliographic works search
- Reference-library adapter: Zotero, read-only
- Run 001: planned and unexecuted

Package releases, run definitions, research records, and export bundles are independently
versioned contracts. A future 1.0 release is intended to mark a clean first public-facing
API/product contract; this release does not otherwise redesign versioning around that milestone.
