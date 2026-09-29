# Lean v1 architecture

The independent architecture audit is the authority for this intervention. Stage 1 reduces the
existing model; later stages build the actual evidence pipeline.

## Retained boundaries

```text
ResearchRequest: what the user asked and optional planning context
ResearchRun: identity, project, original request, plan, lifecycle, timestamps
SearchExecution: the actual provider operation, exact inputs, timing and outcome
SourceDiscovery: how a Source entered a run
Source: a publication with Atlas-owned identity
Study: one study or separable analysis within a Source
Finding: what that Study reported
```

These execution/evidence classes are data records; the dry-run does not populate durable research
work. A small EvidenceAssessment value retains claim-to-finding links and uncertainty without a
history graph. It is not a synthesis engine or a validated claim of support. The later Insight
stage must establish a trustworthy synthesis boundary.

Domain dataclasses represent trusted internal state. Pydantic validates user/project inputs;
provider adapters isolate external formats and query semantics. No provider, consumer, storage
technology, or LLM framework governs the domain.

## Identity and bibliographic attribution

Sources use opaque Atlas UUIDv7 identities. Only explicitly trusted, normalized external keys
and provider-qualified publication IDs support automatic matching. Similar titles or names are
never matching authority. Conflicting strong identifiers fail explicitly.

A LiteratureRecord holds one provider publication observation and its ordered BibliographicCredit
values. Discovery retains every observation, remapping its Source ID after exact reconciliation
while preserving the publication's metadata, provider provenance, and whole credit list. Credits
have no Atlas UUIDs or cross-publication resolution. Supplied ORCID values are metadata only.

The merged display byline comes from the first nonempty observed byline; author strings are never
unioned. Original metadata alternatives remain available. Other display-field selection remains
provisional and is a Stage 2 concern.

Source metadata provenance differs from discovery provenance. A provider supplying metadata need
not be the mechanism that found the Source. Temporary search indices must not become durable keys.

## Flexible information and downstream use

Construct definitions, measurements, instruments, interventions, comparators, moderators, and
quality judgments remain important scientific information. They do not require global identities
or compulsory relationships. Their eventual structured extraction representation is not designed
in Stage 1. Database identity and evidence links must remain relational when persistence is built.

Recommendations, design guidance, coding prompts, and reports are downstream interpretations of
selected evidence. They must preserve attribution and qualifications. Optional consumer settings
do not constrain evidence records or require a promotion lifecycle.

## Removed commitments

Stage 1 removes contributor resolution, global ontology entities, aggregate snapshot persistence,
static export-bundle machinery, compulsory protocol/taxonomy coupling, formal run approval, and
supersession traversal. ADRs 0003-0005 remain historical records, superseded by this intervention.
Semantic Scholar and Zotero are deferred; OpenAlex and optional Crossref remain supported.

## Explicit next work

Stage 2 must address malformed/partial provider results, pagination checkpoints, conflict
isolation, and improved metadata attribution. Later stages must add persistence, identifiable
paper content, validated extractions with exact evidence anchors, evidence-linked Insights,
frontend drill-down, and useful output rendering. No replacement framework is introduced here.
