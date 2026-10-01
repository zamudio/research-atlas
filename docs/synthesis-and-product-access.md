# Synthesis and product access

Stage 4 completes the lean architecture correction using existing dependencies and 14 relations.
There is no bundled LLM provider, extraction engine, HTTP server or frontend. The separate
[one-Source acquisition path](providers.md#openalex-document-acquisition) supports OpenAlex cached
GROBID XML. OpenAlex
remains primary, Crossref optional, and Semantic Scholar/Zotero deferred. No measured coverage gap
justifies provider expansion here. These callables are ready for a later UI adapter.

## Explicit evidence to a published Insight

`application.synthesis.synthesize_insight` receives a `PostgresInsightPublication(engine)` adapter,
a supplied `InsightSynthesizer`, producing run ID, fresh Insight UUID, 1..100 distinct Finding UUIDs,
exact configuration bytes, `RecordProvenance` and an aware publication datetime. The caller retains
these inputs, including UUID and time, for exact retry.

1. Load the explicitly selected evidence packet. Every Finding must belong to the currently selected
   accepted extraction for its Source in this run. Reuse of evidence created in another run is valid
   only through that run's explicit Source selection. Unknown/unselected Findings fail the whole load.
2. Call `await synthesizer.propose(packet, configuration)` outside the publication transaction. It
   returns JSON, not a trusted domain object. A human-supplied proposal can implement the same method.
3. Strict Pydantic validation rejects extra fields, wrong scalar types, blank text and oversized
   lists. The proposal has claim, qualifications, uncertainty_and_limitations, generalizability_notes,
   and relationships (`finding_id`, `relationship`, `rationale`). Text fields have a 20,000-character
   bound; each notes list has at most 100 entries. Roles are supporting, contradicting or contextual.
4. Account for every selected Finding exactly once, without omissions, duplicates or added IDs.
   Require at least one supporting relationship. The role never follows automatically from nullness,
   effect sign or significance. An explicit null result can support a carefully limited claim.
5. Atomically publish. Check the producing run, configuration SHA-256 against exact bytes and current
   accepted selection again under membership row locks ordered by Source ID. A selection change
   during synthesis fails publication. A concurrent selection update waits while publication holds
   those locks. No partial Insight or relationship set survives a failure.

The packet contains typed Finding/Study records, exact anchors, extraction identity/provenance,
document identity/checksum and complete selected Source display metadata. It contains no unrelated
project evidence or entire document payloads. Study content drill-down fetches the exact single
retained document when verification requires it.

Publication adds only four columns to `insights`: publication_status, published_at, configuration
and publication_digest. Its internal draft and final published state commit together. Legacy
schema-only rows remain drafts. Triggers freeze published rows and links, including direct writes.
The canonical publication digest covers claim, notes, provenance, exact configuration bytes,
publication time and complete relationships sorted by Finding UUID. Relationship input ordering is
not content; ordered notes remain content. An identical retry returns without changes, even after
later extraction selection. Different content under the same UUID fails explicitly. New synthesis
results need new UUIDs. No supersession graph or synthesis job table exists.

These checks verify grounding, attribution and explicit appraisal, not scientific truth. A supplied
synthesizer is responsible for interpreting the evidence and stating uncertainty appropriately.

## Seven typed reads

Public functions in `research_atlas.infrastructure.persistence.reads` return dataclasses from
`application.read_models`, never SQLAlchemy rows. `Page(limit=20, offset=0)` requires integer limit
1..100 and offset 0..100000. Lists are deterministically ordered by stable IDs (documents by retrieval
time then ID); successive pages use explicit offsets. Multi-query reads use REPEATABLE READ for a
consistent snapshot within the call. Separate page calls can reflect intervening writes.

| Read | Callable and bounds | SQL statements |
| --- | --- | --- |
| Run/progress | `run_progress(engine, run_id)`; aggregate provider/status search outcomes and all six processing states plus current source screening, including unscreened | 4 |
| Run Sources | `run_sources(engine, run_id, page)`; whole selected display, screening, selected extraction/status, discovery count and earliest discovery context | 1 |
| Source/extraction | `source_detail(engine, run_id, source_id, documents=Page(), attempts=Page(), studies=Page(), findings=Page())`; independently bounded collections, selected extraction always present, Studies/Findings only from that selection | 6 |
| Insight detail | `insight_detail(engine, insight_id)`; publication state/time, claim, caveats, provenance/configuration identity and SQL evidence counts; no passages or configuration blob | 2 |
| Insight evidence | `insight_evidence(engine, insight_id, page)`; published roles/rationales and full historical evidence chain/anchors | 1 |
| Study/content | `study_context(engine, study_id)`; Study and full chain plus that single document's exact bytes, checksum rechecked | 1 |
| Output input | `output_insights(engine, insight_ids)`; 1..20 explicit distinct published IDs in caller order, batched detail/counts/all links, at most 100 links per Insight (2,000 total) | 3 |

Metadata alternatives remain retained but are not exposed by these reads. Source detail lists
documents only for the named Source, attempts created in the named run plus its selected reused
attempt, and selected evidence only. A Source outside the requested run fails. Insight lookup and
Study drill-down intentionally follow historical IDs and do not require current selection. These
are application data boundaries, not authorization APIs; authentication/permissions belong to a
future product layer.

Counts distinguish Findings, distinct Studies and distinct Sources across all roles. Several linked
Findings from a Study produce a dependence warning. Multiple Studies or publications produce an
uncertain-independence/possible-overlap warning. No raw supporting-Finding count is presented as a
count of independent studies. No global Study reconciliation or fuzzy dependence matcher is added.

PostgreSQL tests in `tests/persistence/test_reads.py` instrument statement execution for all seven
reads and compare sizes 5 and 10. Counts above must remain constant. Joins, lateral earliest-discovery
lookup, SQL aggregates and fixed batched queries avoid per-Source/per-Insight lookups. Existing
indexes suffice; no speculative ordering or JSONB indexes were added.

## Generate a cited Evidence Brief

With the database URL configured as described in [database setup](database.md), this callable is
sufficient; no CLI framework or report storage is required:

```python
from uuid import UUID

from research_atlas.application.evidence_brief import render_evidence_brief
from research_atlas.infrastructure.persistence.database import create_database_engine
from research_atlas.infrastructure.persistence.reads import output_insights


async def evidence_brief(insight_ids: tuple[UUID, ...]) -> str:
    engine = create_database_engine()
    try:
        selected = await output_insights(engine, insight_ids)
        return render_evidence_brief(
            selected,
            title="Evidence Brief",
            context="Explicitly selected published research conclusions.",
        )
    finally:
        await engine.dispose()
```

The renderer returns deterministic Markdown for the supplied snapshot; it makes no external calls
or new empirical claims. It includes stable Insight/run identity, claim, qualifications, uncertainty,
generalizability, Study/Source/Finding counts and dependence warnings. Supporting, contradictory and
contextual evidence each have a visible section. Findings retain direction/status, effect estimate,
uncertainty, limitations and moderators. Citations include available title/year/whole ordered byline,
Source/Finding/Study/Extraction/document IDs, document checksum and exact passages/locators.
Missing metadata is labeled, never fabricated. Supplied Markdown/HTML is escaped as visible text.
Source citation display reflects the selected whole metadata observation at read time; historical
evidence identities, content and appraisal links remain immutable.

Unknown/draft Insight IDs fail output loading, rather than producing a partial brief. The renderer
also rejects incomplete relationship sets. Title/context are ordinary caller presentation inputs;
there is no second hidden synthesis step, output table, export aggregate or recommendation lifecycle.
