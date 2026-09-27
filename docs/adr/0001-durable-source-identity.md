# ADR 0001: Durable source identity

## Status

Accepted.

## Context

Research Atlas previously derived `source_id` as UUIDv5 from one preferred bibliographic or
provider identifier. That couples the internal relational identity to incomplete external
metadata: learning a better identifier can change the derived ID. It is therefore unsuitable as a
durable primary key.

## Decision

- `source_id` is an opaque UUIDv7 created for each source candidate. It does not encode source
  metadata and is not an authorization secret.
- External identifiers and `provider + provider_record_id` remain separate, typed exact matching
  evidence. Only explicitly trusted identifier namespaces can trigger automatic matching.
- Pre-persistence resolution merges transitively connected exact-key components only. It retains
  the first-seen candidate's `source_id`; it does not derive another ID from bibliographic data.
- Contradictory DOI, PMID, PMCID, or arXiv values in one exact-connected component raise an identity
  conflict. No fuzzy resolution follows a conflict.

## Consequences

Separate pre-persistence discovery executions may assign different UUIDv7 IDs to equivalent
candidates. Within one execution, exact merging preserves one candidate ID and rewrites temporary
discovery memberships to it. Future persistence will make an already-stored `source_id`
authoritative when resolving new candidates.

## Rejected alternative

Bibliographic or provider identifier-derived UUIDv5 values are not permanent entity identities.
They change when preferred identity evidence changes and conflate external evidence with internal
record identity.

## Deferred

- PostgreSQL tables, repositories, and migrations
- transactional merging of already-stored source rows

Contribution and contributor identity are governed separately by
[ADR 0005](0005-contribution-and-contributor-identity.md).
