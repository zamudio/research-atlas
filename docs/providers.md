# Providers and bounded ingestion

OpenAlex is primary discovery; Crossref is optional complementary bibliographic discovery.
Semantic Scholar and Zotero remain deferred with no active integration.

## Provider-neutral batch contract

LiteratureQuery preserves exact text, ordered parameters and a per-batch limit of 1-100.
LiteratureSource.search(query, checkpoint=None) performs one bounded provider page request, with
bounded HTTP retries. It returns LiteratureBatch(records, next_checkpoint, exhausted, start_position).
The offset is the zero-based count before the page; result ranks are offset + local position.

Null INPUT checkpoint starts a search. exhausted=True plus null NEXT checkpoint terminates it.
A non-exhausted batch requires records and a nonempty checkpoint. A failed request returns no batch.
The adapter validates the entire page before returning anything: a malformed item invalidates that
page, never silently disappears. Earlier successful pages remain intact in the application report.

The checkpoint is an adapter-owned opaque string containing the native next cursor, result offset
and a fingerprint binding it to operation, exact query, parameters and batch limit. Crossref also
binds its select/mailto configuration so resumed wire parameters cannot silently change. Callers must
persist/replay it unchanged with those inputs; changing inputs requires a new search. Tokens do not
contain authorization headers or API keys. This is a small encoding helper, not a pagination engine.

The future atomic step is **persist successful batch observations/identity results/memberships and
persist its next checkpoint in ONE transaction**. Until that commits, retain the input checkpoint.
If the following request fails, retry from the last committed next checkpoint: it still identifies
the failed page. Never advance a checkpoint after a failed/malformed response or failed transaction.
Provider cursors do not promise an immutable remote snapshot or unlimited lifetime. Expiry/replay
changes must be explicit failures/reconciliation cases; never silently restart at page one.

## Discovery outcomes

LiteratureSearchRequest supplies a checkpoint and max_batches (default 1). DiscoverSources collects
at most limit * max_batches records per operation, with providers isolated from one another.

- succeeded: the operation exhausted its available result set (semantic search its bounded set).
- partial: a continuation remains because the budget ended or a later page failed. Preserve earlier
  observations, resolved Sources, ranks, retry checkpoint, completed-batch count and any safe error.
- failed: the first requested batch failed; its input checkpoint remains available for retry.

A resumed invocation counts only its new records/batches; Stage 3 accumulates durable progress once
per committed batch. Successful empty searches remain valid. If all operations fail before a batch
succeeds, DiscoveryFailedError still carries their report. Identity conflicts are a separate report
section, never masquerading as HTTP failure or a resolved membership. A conflict-only valid provider
response is still a successful retrieval with unresolved identity.

## OpenAlex

Lexical search uses /works with exact search text, per_page <= 100 and cursor=*, then each returned
meta.next_cursor. Root object, results list, meta object and explicit next_cursor are required.
Null cursor or an empty valid results list means exhaustion; a short nonempty page with a cursor
continues. Blank nonterminal cursors and oversized pages fail explicitly. Repeated custom
parameters are preserved; adapter-owned search/pagination/authentication parameters cannot override
its choices. The optional API key appears only in the bearer header.

Semantic discovery is a separate bounded single request using search.semantic, at most 50 results
and 2,000 query characters. It validates the results envelope/items, rejects continuation, retains
ranking, and uses shared process-local pacing including retries. These limits are retained adapter
behavior, not claims of newly researched external guarantees.

Work IDs must be present; optional bibliographic fields may be absent/null, but supplied fields must
have valid shapes. Publication raw names take precedence over profile names. All reported ids-map
entries remain observation metadata; known normalized keys alone become matching authority. Top-level
and ids-map DOI disagreement is preserved for conflict detection, not silently overwritten.

## OpenAlex document acquisition

`application.document_acquisition.acquire_source_document` acquires ONE persisted run/Source.
It loads membership and authoritative `source_identifiers` through `DocumentAcquisitionPersistence`,
closes the database read, calls `OpenAlexDocumentAcquirer`, then commits the immutable document and
processing state in one short transaction. There is no run-wide loop, queue or orchestrator.

```python
from research_atlas.application.document_acquisition import acquire_source_document
from research_atlas.infrastructure.config import ProviderSettings
from research_atlas.infrastructure.persistence.evidence import DocumentAcquisitionPersistence
from research_atlas.infrastructure.providers.openalex_content import OpenAlexDocumentAcquirer

# Inside an async caller, with an existing engine, persisted run_id and Source UUID:
document_id = await acquire_source_document(
    DocumentAcquisitionPersistence(engine),
    run_id,
    source_id,
    OpenAlexDocumentAcquirer(ProviderSettings().openalex_api_key),
)
```

Durable OpenAlex provider-record keys are preferred; a normalized external OpenAlex Work ID can
supply the identity when there is no usable provider-record key. Equivalent keys count once.
Zero usable IDs or multiple distinct IDs across either kind fail explicitly before HTTP access.
Display-observation metadata and publisher URLs never choose the acquisition identity.
Source-level exclusions are rejected before retrieval and rechecked under the commit row lock.
At commit, the Source row is locked before the run/Source row, matching discovery reconciliation's
lock order. While holding that lock, acquisition resolves the durable identifiers again and requires
the one unambiguous Work ID to equal the identity used for retrieval. Missing, ambiguous or changed
identity aborts without storing a document or changing processing state. Discovery cannot extend
the Source's identifiers between this revalidation and commit. No lock is held during HTTP I/O.

The only supported representation is `https://content.openalex.org/works/{work_id}.grobid-xml`.
`RESEARCH_ATLAS_OPENALEX_API_KEY` is REQUIRED for this cached-content path and travels only in the
bearer header. URLs and retained context are credential-free. Requests do not follow redirects.
See OpenAlex's [full-text documentation](https://help.openalex.org/access/fulltext/) and
[authentication documentation](https://help.openalex.org/api/authentication/).

The adapter streams application-visible bytes after httpx transport decoding (including gzip),
with a maximum of **32 MiB (33,554,432 bytes)**. For unencoded/identity responses, a declared
Content-Length above the bound aborts before body consumption. For encoded responses (including
gzip), Content-Length describes the transport representation and is not used as the decoded XML
length. Crossing the decoded bound while streaming stops and discards partial content.
Nonempty, well-formed XML is required, without assuming one TEI root shape. Validation uses the
standard-library Expat parser without constructing or normalizing a content tree or fetching
external entities. Exact acquired bytes are retained as `grobid_xml`, `application/xml`, with SHA-256,
retrieval time, source URL and fixed safe outcome context. This does not certify semantic TEI quality.

Three attempts retry 429/5xx and transport failures, using the shared backoff/Retry-After policy
with delay capped at 20 seconds. Each attempt has a 20-second HTTP timeout and async deadline.
404 records `unavailable`; other client/auth errors, malformed/empty XML and exhausted retries
record `failed`. Oversized content records `incomplete`. Remote bodies/exception messages are
never copied into retained context. Non-usable attempts retain no content bytes.

Usable documents atomically set the run Source to `retrieved`, 404 to `unavailable`, and failed or
incomplete results to `failed`. Identical usable content returns the existing durable document UUID;
other outcomes retain distinct immutable attempts. A later usable retry can move failed/unavailable
to retrieved. Selected accepted evidence is retained across processing-state changes.
PDF fallback, TEI normalization and extraction execution remain unimplemented. Run 001 is UNEXECUTED.

## Crossref

/works uses query.bibliographic with cursor=* from the first batch. Every continuation retains all
original parameters, including rows, select, mailto and filters, and sends the newly returned cursor.
A short/empty page exhausts the result set. A full page requires a usable returned message.next-cursor;
absence or blank cursor is malformed, not exhaustion. For a full/nonterminal page, the returned
native cursor must also differ from the request cursor. The Crossref adapter rejects repetition as
malformed_response, retaining the input checkpoint for retry rather than accepting a page replay.
This follows the August 24, 2026 cursor upgrade and September 4 clarification. Batch size is at most 100.

Root/message objects, items list and object work items are validated. Each work requires a nonblank
DOI. Missing optional metadata remains unknown; malformed supplied values fail explicitly. Only
publication dates provide publication year. Credit names/order/ORCID are preserved as metadata.
Repeated filters combine into a comma-separated filter; other repeated parameters retain order.
Adapter-owned parameters and cursor-incompatible date sorts are rejected before HTTP. Optional
RESEARCH_ATLAS_CROSSREF_MAILTO supplies a real contact; none is invented.

## Error safety and limitations

HTTP and transport failures retain bounded retries and Retry-After behavior. Malformed JSON/envelopes/
items/cursors become malformed_response errors with fixed safe text. Unexpected exceptions expose
only their type and a generic message, not arbitrary payloads. Error reports never copy HTTP bodies,
authorization headers or raw validation dumps. HTTP/transport, malformed response, invalid checkpoint,
partial execution and exact-identity conflicts remain distinguishable.

The metadata collector is bounded in-memory developer orchestration. The separate durable ingestion
path reconciles against indexed stored identifiers and commits one batch at a time; it does not
accumulate an entire corpus and run union-find across it. Document acquisition is the separate
one-Source operation described above.
