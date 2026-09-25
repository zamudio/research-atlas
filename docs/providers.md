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
search found that source. A discovery is valid only when the source has provenance for the search
provider, and any discovery provider record ID exactly matches that provider's provenance entry.

## Request safety

OpenAlex sends its optional key only in the authorization header and retains provider-appropriate
retry behavior. Semantic Scholar requests share a 1.1-second in-process coordinator, including
pagination and retries, plus same-machine single ownership for S2-enabled dry runs.

Semantic Scholar honors `Retry-After`. A 429 without it waits 5 seconds before the second attempt
and 10 seconds before the third; 5xx and transport failures retain the shorter generic backoff.
Diagnostics exclude credentials and query contents. Authenticated live canaries belong only in the
user's local checkout; automated tests use mocks and fake clocks.

See the [CLI guide](cli.md) for exact-query handling and request diagnostics.
