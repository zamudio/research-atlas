# ADR 0005: Contribution and contributor identity

## Status

Accepted.

## Context

`SourceRecord.authors` is currently a tuple of normalized bibliographic/display strings. Provider
adapters primarily flatten author data into that tuple, and exact Source merging combines author
strings without resolving the entities receiving bibliographic credit. This is useful display
metadata, but it loses roles and provider context needed for later identity decisions.

Bibliographic credit is broader than human authorship. People may be credited as authors, editors,
or translators, while organizations and collectives may also be credited as authors or in other
roles. A contribution role and the kind of contributor occupying that role are independent
dimensions. The architecture must preserve provider observations before persistence or provider
boundary design fixes a physical representation.

The current providers expose different evidence. OpenAlex structured authorships contain display
names and provider-native Author records and can include ORCID. Semantic Scholar structured authors
contain names and provider-native Author records. Crossref creator metadata can contain structured
names and ORCID. Zotero creator metadata can contain names and explicit creator roles. Current
adapters do not preserve all of this structure.

This decision follows [ADR 0001](0001-durable-source-identity.md): Atlas-owned durable identity is
distinct from external identity evidence. It also preserves the provider-neutral boundary in
[ADR 0002](0002-architectural-boundaries-and-neutrality.md), the observation/provenance distinctions
in [ADR 0003](0003-research-execution-and-provenance-model.md), and the independent contract
versioning rules in [ADR 0004](0004-independent-contract-versioning.md).

## Decision

### Contributions are observed before Contributors are resolved

`ContributionObservation` is the conceptual record of one provider's bibliographic observation
that a named contributor occupied a particular contribution role in relation to a Source. It is
evidence of credited contribution; it is not itself a Contributor.

A contribution observation must be capable of preserving:

- its Atlas-owned `contribution_observation_id`;
- the final Atlas `source_id`;
- the provider-supplied or displayed contributor name;
- the contribution role;
- provider ordering or position where meaningful;
- the provider;
- an optional `provider_record_id`;
- optional external contributor identifiers;
- an optional observed contributor kind; and
- retrieval and provenance context.

Provider ordering is not universally author order. Editors, translators, and other creator roles
must not be forced into author-position terminology. The final field name and role-relative
ordering semantics belong to implementation stage 5B. These information requirements do not
prescribe a Python dataclass or physical storage shape.

### Contribution role and contributor kind are independent

Contribution role describes how an entity was credited in relation to a Source. Examples include
author, editor, translator, compiler, contributor, and other or provider-specific roles. This is
not a closed enum. Future implementation may normalize well-understood roles while retaining
enough provenance to avoid silently changing or discarding provider meaning; this ADR does not
prescribe the representation.

Contributor kind describes the type of entity receiving credit. Useful initial conceptual kinds
include `person`, `organization`, `collective`, and `unknown`. They are descriptive metadata, not
different identity systems or a permanently closed ontology, and `unknown` is valid. Contributor
kind does not determine whether a Contributor may exist or whether exact identity evidence may
resolve observations to it.

For example:

```text
"Jane Smith"        role=author      kind=person
"John Jones"        role=editor      kind=person
"Maria Ruiz"        role=translator  kind=person
"WHO Study Group"   role=author      kind=collective
"World Health Org"  role=author      kind=organization
```

### Contributor identity is Atlas-owned and exact resolution is conservative

A `Contributor` is an Atlas-owned durable identity for an identifiable entity receiving
bibliographic credit for a contribution to a Source. `contributor_id` is its opaque Atlas-owned
identity. It must not be derived from displayed name, role, contributor kind, ORCID, provider
record ID, source ID, or contribution position. External evidence may establish equivalence but
does not become the Atlas primary identity. This ADR does not prescribe a UUID variant or
persistence implementation.

Automatic contributor resolution is authorized only by explicitly trusted exact identity
evidence. This can include:

- normalized ORCID when applicable to an individual;
- exact `provider + provider_record_id` for a provider-native contributor entity; and
- future contributor identifier namespaces that are explicitly trusted when justified.

ORCID is person-oriented external identity evidence, not a universal Contributor identifier. It is
not required for organizational or collective Contributors and is never an Atlas
`contributor_id`. Provider-native contributor records remain provider-qualified evidence rather
than Atlas identity. No Contributor is required to have an external identifier.

Exact evidence can connect contribution observations transitively. If an exact-connected
component contains conflicting strong identifiers, resolution fails closed and requires explicit
adjudication; it must not fall back to names.

Names are bibliographic metadata and observation evidence only. The system must not automatically
merge contribution observations or Contributors solely by exact or case-folded name equality,
initials, given-name/surname similarity, edit distance, transliteration, affiliation, coauthor
overlap, source similarity, embeddings, or LLM judgment. No fuzzy or probabilistic contributor
resolution is authorized. Names may inform later human review, but cannot independently establish
automatic Contributor identity.

A `ContributionObservation` may remain unresolved. If trusted exact evidence or explicit
adjudication is absent, preserving the observation without asserting cross-record identity is the
correct state. The observation retains bibliographic credit and provenance; a name must not be
used to manufacture contributor equivalence.

Organizations and collectives may resolve to first-class Contributors exactly as people may. They
may occupy the same role, such as `author`, and must not be expanded into constituent members
automatically. Membership and organization structure are separate from credited contribution. If
a source credits Alice Smith, Bob Jones, and XYZ Consortium in that order, it has three
contribution observations. A later fact that Alice and Bob are consortium members must not replace
or rewrite that bibliographic contribution statement.

Resolution must be explicit and conceptually separate:

```text
ContributionObservation -> ContributionResolution -> Contributor
```

The resolution relationship must preserve how identity was established, such as trusted exact
identity evidence or explicit manual adjudication. Correction, supersession, and update lifecycle
mechanics are reserved for ADR 0006.

### Provider vocabulary and external evidence remain distinct

Provider-native contributor record identity uses the established canonical term
`provider_record_id`, qualified by its provider and surrounding `ContributionObservation`. The
observation supplies contributor context just as provenance and discovery records supply their own
contexts elsewhere. Synonyms such as `provider_author_id`, `provider_contributor_id`,
`author_record_id`, `person_record_id`, and `external_author_id` must not be introduced unless a
future ADR establishes a genuinely different concept.

External contributor identifiers remain separately governed evidence. Contributor identifiers
must not be conflated with source/publication identifiers merely because both are external. The
final implementation representation belongs to stage 5B.

### Bibliographic strings and provider observations remain available

`SourceRecord.authors: tuple[str, ...]` remains useful normalized bibliographic/display metadata.
These strings do not constitute Contributor identity and need not be removed or redesigned when
structured contribution observations are introduced. Structured observations may eventually
preserve editor, translator, or other roles not represented in the legacy author tuple; not every
`ContributionObservation` must be duplicated into `SourceRecord.authors`.

Exact Source reconciliation and Contributor reconciliation are distinct identity problems. Future
implementation must capture contribution observations from original provider records before
provider-specific detail is lost. When exact Source reconciliation merges candidates, observations
remain attributable to the final Atlas `source_id`, their original provider provenance, and their
original provider-native contributor evidence. Source merging must not collapse distinct
observations merely because their displayed names match. Contributor resolution occurs separately
through trusted exact evidence or adjudication.

Current adapters primarily flatten bibliographic authors into `SourceRecord.authors`. Without new
provider API calls, future structured mapping has these evidence opportunities:

- OpenAlex structured authorships can supply display names and provider-native Author records and
  may supply ORCID when available.
- Semantic Scholar structured authors can supply display names and provider-native Author records.
- Crossref structured creator metadata can supply names and may supply ORCID.
- Zotero creator metadata can supply creator names and explicit creator roles that are
  bibliographically relevant.

These are future architecture implications; the current adapters do not yet preserve every
contributor role or structured identity item.

The domain remains provider-neutral. Future implementation must preserve conceptual separation
among provider observation, contribution role, contributor kind, exact identity evidence, Atlas
Contributor identity, and explicit resolution. This ADR does not select PostgreSQL table names,
SQLAlchemy mappings, repository APIs, or transaction mechanics.

## Consequences

Unresolved contribution observations are a normal, valid outcome. People, organizations, and
collectives share one durable identity concept without conflating their descriptive kinds or their
roles on individual Sources. False contributor merges are avoided at the cost of leaving many
name-only observations unresolved.

This documentation-only decision does not change `SourceRecord`, provider mapping, or any
serialized contract. Whether structured contribution or Contributor records require
ResearchRecords 0.7 will be decided by the stage 5B implementation that changes that contract,
under ADR 0004.

## Deferred

- final Python dataclass design;
- ResearchRecords changes;
- physical PostgreSQL schema;
- SQLAlchemy and Alembic implementation;
- repository and unit-of-work APIs;
- contributor correction, supersession, and update lifecycle semantics, to ADR 0006;
- fuzzy or probabilistic contributor resolution;
- affiliation identity;
- organizational membership modeling;
- manual-review UI; and
- historical migration mechanics.
