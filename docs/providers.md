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

This collector is bounded in-memory developer orchestration, not durable ingestion. Stage 3 must
reconcile against indexed stored identifiers and commit one batch at a time; it must not accumulate
an entire corpus and run union-find across it. No database, download or content processing is here.
