# Providers and safety

## Roles

OpenAlex and Semantic Scholar implement the provider-neutral `LiteratureSource` port and return
normalized `SourceRecord` values. Semantic Scholar relevance search and bulk search are separate
operations with different endpoint semantics; Research Atlas never guesses which one a query
intends. Zotero implements a separate read-only reference-library port.

Crossref is not integrated. A future Crossref adapter can implement the existing literature-source
contract; only Crossref response mapping and provider-specific retry behavior belong there.

## Identity and provenance

Canonical source identity prefers DOI, then PMID or arXiv, then provider namespace plus provider
record ID. Only exact normalized stable identities merge; similar titles are not fuzzily merged.

`SourceProvenance` records metadata origin. `SourceDiscovery` records which logical research
search found that source. These providers and their record IDs may differ—for example, a source
can be discovered manually or through Elicit while its normalized metadata comes from Crossref or
Zotero. `discovery_record_id` belongs to the discovery system and is not matched to metadata
provenance.

`LiteratureQuery.parameters` carries the same generic `(name, value)` data as `SearchSpec` and
`SearchExecution`. Each adapter maps those values into its native request parameters; dry-run
reports retain them for review rather than silently dropping approved logical inputs.

## Request safety

OpenAlex sends its optional key only in the authorization header and retains provider-appropriate
retry behavior. Semantic Scholar requests share a 1.1-second in-process coordinator, including
pagination and retries, plus same-machine single ownership for S2-enabled dry runs.

Semantic Scholar honors `Retry-After`. A 429 without it waits 5 seconds before the second attempt
and 10 seconds before the third; 5xx and transport failures retain the shorter generic backoff.
Diagnostics exclude credentials and query contents. Authenticated live canaries belong only in the
user's local checkout; automated tests use mocks and fake clocks.

See the [CLI guide](cli.md) for exact-query handling and request diagnostics.
