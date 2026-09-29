# Providers

## Supported roles

OpenAlex is the primary scholarly discovery adapter. Crossref is optional complementary
bibliographic discovery. Both implement LiteratureSource and return whole LiteratureRecord
observations containing a SourceRecord and ordered bibliographic credits.

Semantic Scholar and Zotero are deferred. Their adapters, settings, CLI options, specialized
ownership/pacing machinery, and dependency integration are removed from the active implementation.

## OpenAlex

`openalex.search` sends the exact text to `/works` lexical search, with cursor pagination and a
per-operation limit. `openalex.semantic` is a separate optional operation, preserving semantic
query text and result order. Its current adapter allows at most 50 results and 2,000 input
characters; semantic requests use shared process-local pacing, including retries.

These are implemented adapter limits, not a current external service guarantee. Ordinary search
and semantic search have distinct syntax. The adapter must not silently rewrite one into the other.
The optional API key is sent in the authorization header.

Source-specific raw author names take precedence over profile display names when supplied.
Provider author IDs and supplied primary ORCID metadata remain embedded credit data, without
identity resolution or inferred contributor kind.

## Crossref

`crossref.works` sends exact text to `/works?query.bibliographic=...`. This is bibliographic
metadata search, not semantic search or full-text retrieval. Optional
`RESEARCH_ATLAS_CROSSREF_MAILTO` supplies a real contact address; there is no default contact.

The adapter handles cursor pagination, caps pages at 100 items, and preserves generic parameters.
Repeated filter values become one comma-separated filter. Adapter-owned parameters cannot be
overridden; cursor-incompatible sorting fails before a request when pagination is required.

The normalized DOI supplies exact matching evidence and the publication provenance ID. Supplied
credit names and ORCID values are retained without contributor reconciliation. Missing optional
metadata remains empty/unknown; publication dates are not replaced with deposit/index dates.
A missing DOI or malformed required Crossref response fails the operation explicitly.

## Shared behavior and limits

Automatic Source reconciliation uses trusted exact keys only. Metadata provenance stays separate
from search memberships. Original provider observations remain attributable after merging;
merged author lists are never synthesized across providers.

Read-only HTTP calls retain bounded retries, Retry-After handling, safe HTTP/transport errors,
and optional provider pacing. Tests use mocked HTTP and fake clocks; they require no network.

Stage 1 retains the existing whole-search return boundary. Results are accumulated in memory;
there is no persisted cursor or resume behavior. A source identity conflict can still abort the
combined result, and malformed/partial response handling needs further work. Stage 2 owns these
corrections. Metadata discovery must not be presented as completed evidence research.
