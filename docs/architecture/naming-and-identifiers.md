# Naming and identifier glossary

This is the living glossary for current Research Atlas terms. ADRs explain why durable decisions
exist; this document defines what names mean now.

## Core rule

> Atlas-owned entity IDs get one canonical name everywhere; external, transient, and
> provider-owned identities are explicitly qualified.

Never add a new `*_id` name if an existing concept already owns that meaning. Do not mechanically
prefix all Atlas-owned identifiers with `atlas_`; the established entity-specific name is the
canonical name.

## Identifier terms

### `source_id`

Atlas-owned durable `Source` identity. It is opaque and independent of bibliographic metadata,
external identifiers, and provider record identifiers. Normal new Atlas source creation generates
a UUIDv7. Exact identity evidence may establish equivalence and merge candidates while preserving
an existing Atlas `source_id`; later metadata must not cause persistence to recompute it.

### `provider_record_id`

Canonical concept and name for provider-native record identity involved in an observation or
discovery. It is qualified by provider and is not Atlas Source identity.
`SourceProvenance.provider_record_id` identifies a metadata-provenance record. Current code also
uses `SourceDiscovery.discovery_record_id` to carry provider-native identity captured during
discovery; that existing field is not a second canonical identifier concept and does not authorize
additional `*_record_id` synonyms. Future persistence or contract work must consult this glossary
before retaining, renaming, or introducing identifier terminology.

### `external_identifier`

Externally governed identifier such as DOI, PMID, PMCID, arXiv ID, or ORCID, depending on the
entity and context. A normalized identifier in an explicitly trusted namespace can be exact
identity evidence, but it remains external evidence rather than an Atlas-owned entity ID.

### `search_spec_id`

Identity of an intended search specification in a `RunDefinition`.

### `search_execution_id`

Identity of an actual logical execution of an intended search. A durable discovery points to this
identity, not to the requested search's temporary list position.

### `discovery_id`

Durable Atlas-owned identity of a `SourceDiscovery`.

### `search_index`

Temporary, zero-based, in-memory position of a requested search in an application discovery
operation. It must be resolved to the corresponding `search_execution_id` before persistence and
must never become a durable relational identity or foreign key.

### `result_position`

Provider-returned one-based result rank within a requested search. It describes discovery context;
it is not source or discovery identity.

## Structural suffixes

### `*_reference`

A pointer or reference to an artifact, not an entity identity. For example, a definition reference
locates the project-owned artifact associated with a run.

### `*_fingerprint`

A content-derived integrity value, not an entity identity. For example, a definition fingerprint
verifies the exact validated definition state executed by a run.

### `*_snapshot`

Immutable captured state. A snapshot preserves the contract as it existed at a boundary; its
contents are not a mutable live definition.

## Naming guardrails

Near-synonyms such as `canonical_source_id`, `external_source_id`, `provider_source_id`,
`stable_source_id`, and `source_record_id` must not be introduced unless they represent a genuinely
distinct architectural concept. Qualify external or provider-owned identifiers by what owns them;
do not rename the Atlas-owned `source_id` to restate that it is canonical or stable.

Illustrative relational naming should use entity-specific canonical names, for example:

- `sources.source_id`
- `research_runs.run_id`
- `search_executions.search_execution_id`
- `source_discoveries.discovery_id`

Avoid generic examples such as `sources.id`. These examples communicate naming only; they do not
specify a physical database schema.
