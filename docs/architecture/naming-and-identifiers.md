# Naming and identifiers

Use one name per identity. Do not derive Atlas identity from mutable bibliographic metadata.

| Name | Meaning |
| --- | --- |
| `source_id` | Opaque Atlas UUIDv7 identifying a publication across providers and runs. |
| `provider_record_id` | Provider-owned identity, qualified by provider and record context. |
| `external_identifiers` | Registry/provider evidence, such as DOI or PMID; not Atlas identity. |
| `run_id` | Identity of an actual research effort owned by a project. |
| `search_execution_id` | Identity of an actual logical search, independent of a planned list position. |
| `discovery_id` | Identity of a Source's discovery through a search execution. |
| `study_id` | One study or clearly separable analysis reported by a Source. |
| `finding_id` | One result reported by a Study. |
| `search_index` | Temporary zero-based position in a discovery request; never a durable FK. |
| `result_position` | One-based provider result rank; not Source identity. |

SourceProvenance identifies the provider publication supplying metadata. SourceDiscovery describes
how a Source entered a run; its provider record may differ. A BibliographicCredit may retain a
provider's contributor-record ID, but it is embedded in a whole publication observation and has no
Atlas person/organization identity. Credit tuple order retains the supplied byline order.

Separate discovery calls may assign different candidate Source IDs. Exact reconciliation keeps
the first candidate ID within a call. Stored-ID reuse and transactional reconciliation are future
persistence work; callers must not assume present discovery already provides cross-run durability.
