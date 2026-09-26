# ADR 0004: Independent contract versioning

## Status

Accepted. This ADR records the existing versioning contract.

## Context

Research Atlas has a software distribution and several serialized contracts. They serve different
consumers and do not necessarily change together.

## Decision

The following versions evolve independently:

| Contract | Current version | Repository authority |
| --- | --- | --- |
| Python package/software | `0.6.0` | `pyproject.toml` |
| `RunDefinition` schema | `0.2` | `RunDefinition.schema_version` |
| `ResearchRecords` schema | `0.5` | `ResearchRecords.schema_version` |
| `ExportBundle` schema | `0.1` | `ExportBundleManifest.bundle_schema_version` |

Persistence and PostgreSQL development belongs to the software `0.6.x` line. That work does not by
itself require `ResearchRecords` to become `0.6`, nor does a package release force any serialized
schema to adopt the same number.

A serialized schema version changes only when that serialized contract changes. Conversely, a
schema may evolve when its own contract requires it, independently of the package, other schemas,
or the storage implementation.

## Consequences

Release notes and documentation must name the contract whose version changed. Readers must not
infer serialization compatibility from the package version alone. Persistence work must consume
the established schema contracts without renumbering them merely to align version labels.
