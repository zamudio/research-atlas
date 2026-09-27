# Providers and safety

## Roles

OpenAlex and Semantic Scholar implement the provider-neutral `LiteratureSource` port and return
normalized `SourceRecord` values. `openalex.search` is ordinary lexical discovery;
`openalex.semantic` is natural-language semantic discovery and is the preferred product-safe
semantic candidate currently being evaluated for Research Atlas. Semantic Scholar relevance
search remains an optional/internal comparator, and its relevance and bulk searches remain
separate operations with different endpoint semantics. No Research Atlas core contract depends on
Semantic Scholar. Zotero implements a separate read-only reference-library port.

## OpenAlex discovery operations

Both OpenAlex operations use `/works` and the same `SourceRecord` normalization. Lexical discovery
maps the exact query to `search`; semantic discovery maps it to `search.semantic` without rewriting
it into Boolean, ordinary-search, or exact-search syntax. Semantic search is one provider-ranked
result set with a maximum of 50 results and a provider limit of one semantic request per second;
requests above 50 fail before network access rather than reporting a silently truncated result.
Adapter-owned search-mode, result-limit, selection, and cursor parameters cannot be overridden.

Under ordinary OpenAlex `search`, `?` and `*` are wildcard syntax and may be rejected unless exact
search semantics are used. The lexical adapter does not silently strip or rewrite approved query
text to avoid that provider behavior.

Crossref implements the same port as an **experimental feasibility adapter**, `CrossrefWorksSearch`
(`crossref.works`). It is for bibliographic discovery and metadata verification, not a replacement
for semantic search. Independent diff review and small local canaries have completed successfully;
Crossref remains experimental pending an explicit permanent-role decision. No Run 001 execution is
part of this spike.

## Experimental Crossref access and mapping

The [public Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
requires no signup or paid token. Metadata Plus is not implemented. The adapter identifies itself
with a generic User-Agent; optional `RESEARCH_ATLAS_CROSSREF_MAILTO` supplies your contact address
via `mailto`. No default address is supplied. Public metadata access does not imply full-text access.

`LiteratureQuery.query` maps exactly to `/works?query.bibliographic=...`. Generic parameters
(including repeated names) are forwarded, except repeated `filter` values are preserved in order
and serialized as Crossref's single comma-separated `filter` value. `query.bibliographic`,
`rows`, `cursor`, `select`, and `mailto` are adapter-owned; collisions raise `ValueError`.
`offset` and `sample` are also rejected
because [Crossref cursors cannot be combined with them](https://github.com/CrossRef/rest-api-doc).
Single-page requests do not use a cursor. Cursor pagination is sequential, at most 100 items per
request, carries all non-cursor request parameters unchanged across pages, uses the newly returned
cursor token for the next page, and trims results locally to the logical limit. Sorts by `issued`,
`published`, `published-print`, or `published-online` are allowed for single-page requests but
fail before network access when cursor pagination would be required. The existing HTTP retry helper
honors `Retry-After`; no S2 coordinator or ownership guard is acquired for Crossref, and no
throughput guarantee is assumed.

The normalized DOI supplies both exact identity evidence and the Crossref provenance record ID. No
fuzzy matching is added. Missing titles remain empty, authors empty, year/URL null, and type
`unknown`.
Publication year uses the first usable `published`, `published-print`, `published-online`, or
`issued` year; deposit/index dates are never substituted. The first nonblank title and supplied
author names are preserved, without inferring affiliations, missing authors, or landing URLs.
A missing DOI or malformed response fails the operation explicitly rather than inventing identity
or silently reporting incomplete results. Existing discovery reporting exposes provider failures.

## Identity and provenance

`source_id` is an opaque UUIDv7 internal entity ID. It is independent of DOI, PMID, PMCID, arXiv,
provider record IDs, and other bibliographic metadata. Trusted normalized external identifiers and
typed `provider + provider_record_id` pairs supply exact match keys; unknown identifier namespaces
remain metadata rather than gaining automatic match authority. Transitively connected exact keys
merge, while contradictory DOI, PMID, PMCID, or arXiv evidence fails explicitly. Similar titles are
not fuzzily merged.

`SourceProvenance` records metadata origin. `SourceDiscovery` records which logical research
search found that source. These providers and their record IDs may differ—for example, a source
can be discovered manually or through Elicit while its normalized metadata comes from Crossref or
Zotero. `SourceDiscovery.provider_record_id` belongs to the discovery system and need not match
`SourceProvenance.provider_record_id`, which identifies the record that supplied normalized
metadata.

`LiteratureQuery.parameters` carries the same generic `(name, value)` data as `SearchSpec` and
`SearchExecution`. Each adapter maps those values into its native request parameters; dry-run
reports retain them for review rather than silently dropping approved logical inputs.

## Contribution observations

The current adapters normalize provider author names into `SourceRecord.authors`; those strings
remain bibliographic/display metadata and are not Contributor identity. Future structured mapping
can capture contribution observations before detail is flattened and retain their role, meaningful
provider ordering, original provider, and provider-native contributor evidence after exact Source
merging. Displayed-name equality must not collapse observations.

OpenAlex authorships can supply display names, provider-native Author records, and ORCID when
available. Semantic Scholar authors can supply display names and provider-native Author records.
Crossref creator metadata can supply structured names and ORCID. Zotero creator metadata includes
bibliographically relevant creator names and explicit creator roles. Current adapters primarily
flatten authors and do not yet preserve every role or identity item; these architecture
opportunities require no new API calls.
[ADR 0005](adr/0005-contribution-and-contributor-identity.md) defines the Contributor identity and
resolution contract.

## Request safety

OpenAlex sends its optional key only in the authorization header and retains provider-appropriate
retry behavior. OpenAlex semantic discovery is currently limited by the provider to one request
per second. Semantic Scholar requests share a 1.1-second in-process coordinator, including
pagination and retries, plus same-machine single ownership for S2-enabled dry runs.

Semantic Scholar honors `Retry-After`. A 429 without it waits 5 seconds before the second attempt
and 10 seconds before the third; 5xx and transport failures retain the shorter generic backoff.
Diagnostics exclude credentials and query contents. Authenticated live canaries belong only in the
user's local checkout; automated tests use mocks and fake clocks.

See the [CLI guide](cli.md) for exact-query handling and request diagnostics.
