# Research lifecycle

ResearchRequest captures what the user asked and optional planning context. ResearchRun owns the
project, original request, lifecycle and timestamps. SearchExecution records what actually ran.
The current diagnostic does not instantiate/persist these execution records. Run 001 is UNEXECUTED.

## Discovery and progress

Fetch one validated bounded LiteratureBatch using the previous checkpoint. Preserve observations,
resolve exact components, and retain conflict cases without inventing resolved Source IDs. A future
transaction must commit those results together with the next checkpoint. Only then fetch another
page. In-memory DiscoverSources reports bounded succeeded/partial/failed outcomes today.

SearchExecution's requested_limit is the per-batch limit. completed_batches and provider_result_count
are durable cumulative progress in Stage 3; the diagnostic reports counts for its invocation only.
A partial status pauses an incomplete execution with checkpoint and optional safe error metadata.
completed_at on partial records marks the end of that invocation, not exhaustion of the search;
resuming the same logical search sets running and clears that time. Exact inputs never change.

RunSource.processing_state independently records discovered, retrieved, extracted, excluded,
unavailable or failed coverage for each run/Source. Current screening state and reasons come from
ScreeningDecision values on that membership, not a screening history table. Future progress reads
combine indexed search outcomes and membership states; a successful search does not imply that its
Sources were retrieved or extracted. State updates are explicit and do not clear accepted selections.

## Content and extraction

SourceDocument identifies an immutable version of anchorable content with Source, kind, checksum,
retrieval context/time and usability status. A changed parsed text or payload is a new version.
Extraction records one attempt against exactly that version, creating run, purpose, configuration
hash, tools/models, timing and validation/review outcome. These are contracts, not download/extraction
services. Instruction and configuration bytes must be retained alongside their hash in Stage 3.

Queued/running attempts are distinct from accepted, review_needed, failed and rejected results.
Finalized attempts cannot be overwritten. A rerun creates a new extraction identity even if its
inputs/configuration match. Review acceptance requires validated output; failed/review-needed
attempts cannot become selected run evidence merely because output exists.

A RunSource can explicitly select one accepted extraction for a Source. Selection does not combine
all extraction attempts. StudyRecord.extraction_id owns the study set; FindingRecord.source_study_id
owns each result, with an exact passage and/or locator in the document selected by that extraction.
No page number is mandatory. Source and Study remain different entities.

## Synthesis and use

Insight is one cross-finding claim, with producing run and synthesis configuration/provenance.
InsightFinding records supporting, contradicting or contextual relationships with an explicit
rationale. Null/uncertain is a Finding property, not an evidence-link role. A positive result does
not automatically support a claim; nonsignificance does not automatically contradict one.

Once an Insight references a Finding, later extraction selection changes cannot silently redirect
that link to newer evidence. Old finalized extraction content remains available for drill-down.
Generated summaries, recommendations, reports and coding prompts are downstream renderings of
selected Insights and their qualifications; no application promotion ontology is required.

## Acceptance examples

Executable cases are in test_source_identity.py, test_discovery.py, test_batches.py and
test_evidence_contracts.py under tests/unit:

- A: DOI-connected records with contradictory strong IDs are quarantined; an unrelated Source survives.
- B: providers disagree on title/year/byline; the first entire observation is displayed and identified.
- C: pages 1/2 succeed and page 3 fails; partial data survives and replay requests page 3 again.
- D: HTTP 200 with {} or malformed items/meta/message is a provider failure, never empty success.
- E: extracting one document twice creates two immutable identities; a run explicitly selects one.
- F: Finding -> Study -> Extraction -> exact SourceDocument, with passage/locator anchoring.
- G: null results receive relationship roles only through explicit appraisal decisions.

[Stage 3 persistence semantics](persistence-boundary.md) defines the required constraints and read
paths. No whole-project hydration or unbounded history traversal is part of these contracts.
