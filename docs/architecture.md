# Lean v1 architecture

The independent architecture audit remains the authority. Stage 1 removed speculative machinery;
Stage 2 settles ingestion/provenance behavior and small content/evidence contracts. Persistence,
content acquisition, extraction execution, synthesis generation, and frontend/API remain unbuilt.

## Boundaries and retained records

ResearchRequest expresses user intent and optional planning. ResearchRun owns the original request,
project and lifecycle. SearchExecution records actual provider/operation/query/parameters, per-batch
limit, progress count, checkpoint, timing and safe errors. These are distinct from intended plans.

LiteratureSource returns one LiteratureBatch per call. The application can collect an explicitly
bounded number of batches. Provider response models remain private to adapters; native cursors
are opaque outside them. Domain records are trusted dataclasses; provider/user boundaries validate
external data. No provider, storage technology, consumer, or LLM framework governs the domain.

## Attributable observations and Source identity

LiteratureRecord is one metadata observation with a UUIDv7 observation_id, one provider publication
provenance (provider, optional publication-record ID, required retrieval time), reported identifiers,
complete ordered credits/byline and all display fields. Empty credit names retain an unnamed slot;
contributors have no Atlas identity. Provider ORCID values remain unverified credit metadata.

The embedded SourceRecord is a provisional candidate snapshot, not a persisted Source row. It is
unchanged during reconciliation. resolved_source_id is separate and remains null for conflicts.
Stage 3 persists the observation's fields and resolved FK, not the provisional candidate UUID.

Resolved Sources use Atlas UUIDv7 identity. Only trusted normalized external identifiers and
provider-qualified publication keys drive exact matching. Unknown identifiers stay on observations;
they are not promoted to authoritative Source identifiers. The original reported strings remain
available even when normalized keys are used for matching. DOI/PMID/PMCID/arXiv conflicts quarantine
the entire transitive component, including its otherwise unambiguous members. Other components
survive. Conflict reports identify observation IDs and contradictory normalized namespace/values;
conflicted memberships have no resolved Source ID. No fuzzy matching is performed.

Display selection is deliberately simple: the FIRST observation in request order, then provider
page/result order, supplies title, year, complete byline, type and URL together, including missing
fields. Network completion order cannot change the choice. Source.display_observation_id identifies
that exact observation. All alternatives are retained. Identifiers and provider provenance may be
combined for identity/attribution, but display fields are never combined. Local repeated resolution
of the same inputs is deterministic; newly fetched observations have new provisional UUIDs. Stored
ID reuse and replay idempotency belong to the explicit Stage 3 rules.

Metadata provenance and discovery provenance differ. An observation may come from a different
provider than the search that found it. DiscoveryMembership records the actual search index, rank,
observation ID and nullable resolved Source ID; resolved duplicates retain the first rank per
search. Original duplicate observations are still available. Temporary indices are not durable IDs.
Durable SourceDiscovery carries the required observation_id alongside its resolved Source, search/run,
discovery time and rank. Conflicted observations do not produce a fake durable discovery.

## Content, extraction and evidence contracts

SourceDocument identifies one Source's content artifact/version, its kind, retrieval context/time,
optional URL/media type, SHA-256 of the exact anchorable bytes, and usable/unavailable/failed/incomplete
status. Usable content requires a checksum. Replacing bytes or the parsed representation creates a
new document identity. A mutable remote URL is never an immutable content reference.

Extraction identifies one attempt against that document ID, creating run, purpose, instruction plus
configuration hash, tool/model names and versions when used, timing, lifecycle and validation/review
outcomes. Accepted output requires passed validation and an explicit accepted/not-required review
disposition. Failed and review-needed output cannot be selected as evidence. Re-extraction creates a
new identity; finalized attempts remain immutable and addressable. Configuration hashes refer to
retained exact instruction/configuration bytes, not a protocol registry.

RunSource.select_extraction explicitly selects at most one accepted extraction of a usable document
for that Source. It can reuse an accepted result from another creating run. Replacing this selection
does not destroy earlier attempts. Active run evidence reads traverse the selected extraction, so
repeated execution alone cannot inflate the number of independent studies.

RunSource also records current run-specific processing_state: discovered, retrieved, extracted,
excluded, unavailable or failed. This is separate from provider/search outcomes. State is explicit;
select_extraction does not rewrite it, and a later failure may retain earlier accepted evidence.
Current ScreeningDecision data maps to screening state/reasons on run_sources, without a separate
screening history table. See the persistence boundary for source-level versus study-scoped screening.

StudyRecord has an explicit extraction_id. FindingRecord references its Study and requires at least
one EvidenceAnchor: exact passage and/or plain-text locator in that extraction's document. Page
numbers are optional; sections/tables are ordinary locator text. Stage 3 must enforce consistent
Source/Extraction/Study links, not infer them from the prose in RecordProvenance.

Insight replaces the temporary assessment record. Each Insight is one claim with producing run,
qualifications, uncertainty/generalizability and reproducible synthesis configuration/provenance.
InsightFinding is an explicit supporting/contradicting/contextual decision with rationale. Finding
nullness or statistical direction never chooses that relationship. These records do not generate
claims or validate empirical support; accepted evidence links require validation at future execution
and persistence boundaries.

## Flexible detail and downstream outputs

Study/Finding details are structured mappings for scientific information, eventually controlled
JSONB validated by the extraction boundary. Constructs, instruments, interventions, comparators,
moderators and outcomes do not gain global identities. Trusted dataclasses are not probabilistic
output validators and do not deeply freeze nested mappings. Persisted finalized evidence must be
immutable. Recommendations, design guidance, prompts and reports remain downstream renderings.

Stage 1 deletions remain in force. Semantic Scholar and Zotero remain deferred. No replacement
snapshot/export aggregate, identity ontology, protocol/version registry, or worker framework exists.
ADRs 0001/0002 remain central; ADRs 0003-0005 remain superseded history.

See [provider behavior](providers.md), [lifecycle](research-lifecycle.md), and the
[Stage 3 persistence boundary](persistence-boundary.md) for transactions, uniqueness and query paths.
