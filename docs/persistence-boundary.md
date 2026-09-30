# Stage 3 persistence boundary

This is the approved lean relational spine and its acceptance semantics. Stage 2 implements
contracts and bounded ingestion only. No database library, repository, migrations or UoW is added.

## Relations and ordinary reads

| Relation | Identity, links and purpose |
| --- | --- |
| projects | Project identity and optional reusable research context. |
| research_runs | Run identity; project FK; original request, optional plan and progress. |
| search_executions | Search identity; run FK; immutable actual operation/inputs, batch limit, checkpoint, count and status. |
| sources | Atlas UUID; selected display observation FK. Display fields are that observation's projection. |
| source_identifiers | Authoritative exact keys with Source FK; typed external namespace or provider publication scope. |
| source_metadata_observations | Observation UUID; nullable resolved Source FK, provider/publication/time, complete ordered credits and reported fields/IDs. Conflicts remain unresolved observations. |
| run_sources | Unique run/Source pair; current processing_state, current screening/reason detail, and optional selected accepted extraction FK. |
| source_discoveries | Discovery identity, SearchExecution/run/resolved Source FKs, required observation_id FK, discovery time and first result rank; separate from metadata provider. |
| source_documents | Immutable document UUID/version; Source FK; kind, exact-byte checksum, retrieval context and usability. |
| extractions | Attempt UUID; creating run and document FKs; purpose, exact configuration hash, tool/model identity, validation/review and status. |
| studies | Study UUID; Source and extraction FKs; stable study context and flexible detail. |
| findings | Finding UUID; Study FK; reported result/uncertainty, anchors into its extraction document and flexible detail. |
| insights | Claim UUID; producing run FK, configuration/provenance and qualifications. |
| insight_findings | Unique Insight/Finding pair with explicit role and rationale; both FKs required. |

No contributor, construct, measurement, intervention, taxonomy, protocol, application or export tables.
There is no separate screening-decision history table; the approved spine remains 14 relations.
No extra conflict entity/table is required: observations and search batch outcomes can retain bounded
conflict details for review. Domain/source terminology maps to these relations without giant aggregates.

## Source identity lookup and concurrency

Normalize only the explicitly trusted keys in source_identity.py. Each authoritative key is unique
on (kind, namespace, value), not merely within a run. Provider publication keys use kind=provider_record,
namespace=provider and the provider's publication ID; author IDs never enter this index. External keys
have kind=external_identifier and normalized namespaces. These two key kinds cannot collide. Untrusted
reported keys stay in observation data, never this index. Strong DOI/PMID/PMCID/arXiv contradictions
prevent promotion of the entire conflicting component's keys.

For each bounded component, look up its keys using the unique index. Reuse a single stored Source ID
only if the complete stored+incoming authoritative identifier set is conflict-free. Add new keys and
observations transactionally. No match creates one Atlas UUID plus its keys in the same transaction.
Concurrent creators race on the authoritative-key uniqueness constraint: the loser rolls back, rereads
the winner and rechecks all strong identifiers before reusing it. Never ignore a uniqueness violation
and attach the observation to whichever Source happened to win.

If keys already refer to several persisted Sources, quarantine that component for explicit duplicate
resolution; do not automatically choose an ID or rewrite evidence FKs. Later reviewed consolidation
must atomically choose a surviving ID, move identities/memberships/links consistently, preserve original
observation/content provenance and leave old references addressable. Redirect implementation is deferred;
Stage 3 can block that component while continuing unrelated components. Keyless observations get their
own Source unless replay identity proves they are the same observation; titles/content similarity never
become Source matching authority.

Persistent reconciliation uses indexed key lookups and local bounded components, never a full-corpus
in-memory union-find. The Stage 2 resolver's first candidate UUID is only an in-memory provisional ID.
The selected display observation must belong to the same resolved Source; create/attach/select it
in one transaction (a temporarily null display FK may be needed while inserting).
For stored display metadata keep the initially selected valid observation stable. Explicit replacement
may select another whole observation; never update individual display fields from different snapshots.

## Idempotency and uniqueness

| Item | Required Stage 3 behavior |
| --- | --- |
| Source identifier | Global unique typed exact key; canonical Source FK only after conflict checks. |
| Metadata observation | Deduplicate unchanged snapshots by provider + nonblank publication ID + canonical reported-content hash (all display fields, ordered credits and raw IDs; exclude candidate UUID and retrieval time). Reuse observation UUID; retain first retrieval time and separate last-seen information if needed. Changed metadata creates a new observation. |
| Keyless observation | Replay identity is search execution + input checkpoint + page position; do not collapse different keyless publications merely because their content hashes match. |
| run_sources | Unique (run_id, source_id); screening and selected extraction belong to this membership. |
| SourceDiscovery | Unique (search_execution_id, source_id), with first rank and required observation_id; repeated provider observations still remain individually stored. Enforce search/run ownership and observation/resolved-Source consistency. |
| Batch progress | Commit once per (search_execution_id, input checkpoint), including a distinct initial marker. Preserve payload digest and records with the next checkpoint; replay of an already committed batch returns its committed result without incrementing counts. |
| SourceDocument version | For available bytes, deduplicate (source_id, content_kind, content_sha256); checksum covers the exact representation used by anchors. Failed/unavailable attempts use their document UUID for retry idempotency until usable content exists. Never overwrite finalized bytes/checksum. |
| Extraction attempt | Caller-assigned extraction UUID is the retry key. A deliberate re-extraction has a NEW UUID even for identical document/configuration. Do not make document/configuration globally unique. Finalized rows and their evidence stay addressable. |
| Insight/Finding link | Unique (insight_id, finding_id) with one explicit role/rationale; result direction/nullness is not a role derivation rule. |

Canonical observation payloads preserve list order and exact reported identifier values; serialization
rules must be deterministic. If replay of an uncommitted page returns changed remote content, ingest the
validated page as the retry result without claiming snapshot consistency. If an already committed batch
key is presented with a different payload digest, expose a replay mismatch and retain the committed
batch/checkpoint; do not overwrite history or silently inflate counts. Cursor expiry is visible, not a
license to skip/restart. These database guarantees are specified, not implemented in Stage 2.

## Atomic boundaries

1. Source key lookup/create, authoritative identifier promotion and observation attachment are one
   atomic identity operation. Conflicted components attach to no canonical Source. Concurrency must
   recheck complete strong-key sets after locks/unique-key retries.
2. All successful page observations (including unresolved conflict records), resolved memberships/
   discoveries, conflict details, cumulative counts, completed-batch marker and NEXT checkpoint commit
   together. Use the expected INPUT checkpoint as a compare-and-set condition so concurrent callers
   cannot advance one logical search twice. A failed transaction leaves the input checkpoint unchanged.
   Local savepoints or equivalent conflict handling let unrelated components remain in the batch.
3. Finalizing an extraction and publishing its validated Study/Finding rows/anchors is atomic. Enforce
   that Study.source_id equals Extraction.document.source_id. Only usable immutable documents can
   back accepted extraction evidence. Finalized evidence is immutable; reruns create separate attempts.
4. Changing run_sources.selected_extraction_id is explicit and atomic after checking acceptance and
   Source ownership. Active run evidence joins only that selection; old finalized evidence stays intact.
5. Publishing an Insight with its appraised Finding relationships is atomic. Require existing accepted
   extraction evidence and provenance for each empirical relationship. Existing Insights retain their
   exact Finding links when a run later selects a different extraction. Deletion cannot dangle links.

No lease, distributed lock, job queue or repository abstraction is implied by these requirements.
Partial SearchExecution state records a checkpoint, count and optional error. A provider error occurs
outside the ingestion transaction and cannot roll back already committed pages.

## Current run-specific progress and screening

RunSource.processing_state is one of discovered (initial resolved membership), retrieved (usable
content obtained or reused), extracted (accepted extraction selected for this run), excluded (not
eligible for this run), unavailable (no usable content available), or failed (source-processing
attempt failed). These are current outcomes, independent of SearchExecution's provider/search status.
There are no in-progress variants, jobs or transition engine. The same Source may have different
processing states in different runs. Stage 3 explicitly writes the state with the relevant result.

Extraction selection keeps its existing acceptance/Source checks and changes only the selected ID;
it does not infer processing state. A caller records extracted explicitly when recording that outcome.
A later processing failure can retain earlier accepted evidence. Progress counts describe current
processing dispositions, not the lifetime number of successful retrieval/extraction attempts.

ScreeningDecision remains a lightweight input/current value. A source-level decision maps its decision,
reason_codes, rationale and record_provenance to current screening fields on the matching run_sources
row; decision_id identifies that current assessment, not an append-only history entity. A null current
screening decision means unscreened. Enforce matching run_id/source_id. Applying a source exclusion
updates current screening and processing_state=excluded atomically. Include/uncertain/defer/duplicate
decisions do not by themselves prove retrieval or extraction success. Study-scoped decisions retain
their study_id as scoped current detail on the same membership, without automatically excluding the
whole Source or overwriting source-level screening. No independent screening history table is added.

SourceDiscovery.observation_id identifies the specific metadata observation associated with the
resolved discovery. Its Source FK must match that observation's resolved Source. Discovery time,
SearchExecution/run and rank describe discovery; the linked observation retains its own metadata
provider/retrieval time. A provider_record_id belongs to the discovery provider when applicable, not
an unrelated metadata provider. Conflicted observations have no durable SourceDiscovery until resolved.

## Flexible data and content anchors

Project context, ordered credits/reported identifiers, extraction configuration, scientific details,
locators and qualifications are controlled structured data / future JSONB. Validate probabilistic
extraction output at its boundary before creating trusted records. Do not turn fields such as construct,
instrument, intervention, comparator or moderator into global identities/tables. Relational FKs preserve
stable identity, workflow ownership and evidence links; JSONB must not replace those relationships.

Configuration hashes require retained exact instruction/settings bytes; model/tool identity records
versions when used. Store exact anchorable document bytes and verify content_sha256 when reading them.
A passage must match that document (or be explicitly marked unverified in review-needed output);
accepted Findings cannot use an anchor into another extraction's content. Locators need not be pages.

## Seven frontend/query paths

| Read | Bounded indexed access |
| --- | --- |
| Run and progress | research_runs + grouped search_executions search outcomes + run_sources counts grouped by processing_state and current source-level screening decision. Count all memberships for discovered coverage, then retrieved/extracted/excluded/failed/unavailable current dispositions. |
| Run Sources | run_sources filtered by run, paginated Source/display-observation join. |
| Source and extraction | Source + paginated documents/attempts; selected extraction from requested run_sources row. |
| Insight | Direct Insight UUID lookup with producing run/provenance. |
| Insight evidence | Paginated insight_findings -> findings -> studies -> extractions; batch fetch related IDs. |
| Study/Source/content | Study -> Extraction -> SourceDocument and Source via fixed FKs; anchors stay local to that version. |
| Generated output | Selected Insight IDs + batched evidence/qualification reads; downstream rendering only. |

Index run_sources by (run_id, processing_state) and (run_id, current screening decision), plus
search_executions by (run_id, status). Read #1 combines those database aggregates for searched and
source-processing/screening coverage without loading all observations, documents or findings.
Index foreign keys and pagination/order fields used by the remaining paths. Avoid N+1 per-source/per-finding
loads by joining or fetching bounded ID sets. None requires whole-project hydration, supersession graph
traversal or rerunning identity resolution on every read. Detailed SQL/index design belongs to Stage 3.
