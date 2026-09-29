# Research lifecycle

## Ask and plan

A ResearchRequest needs only a nonblank question. Subquestions, constraints, plan notes, and
expected outputs are optional. Loading request YAML does not approve or execute research.
ProjectProfile supplies project identity and optional research context.

ResearchRun retains the original request and planning information with project ownership,
lifecycle state, and timestamps. Intent can differ from execution; an evolving plan must not
rewrite what actually happened.

## Discover

The implemented DiscoverSources use case executes explicit provider operations and preserves
exact query text, parameters, limits, outcomes, and temporary memberships. It retains provider
publication observations alongside reconciled Sources. One provider failure does not erase another
provider's results. A successful empty response and an explicit provider failure are distinct.

The CLI is metadata-only. It creates neither ResearchRun nor SearchExecution nor SourceDiscovery.
For future durable execution, SearchExecution records actual inputs/outcomes and SourceDiscovery
links Sources to those executions. Search indices are temporary in-memory coordinates.

## Screen and extract: future workflow

ScreeningDecision represents run-specific eligibility, including uncertainty, rationale, and an
optional Study subject. It has no supersession graph. Source and Study remain distinct: a paper
can contain several studies. FindingRecord retains reported results, uncertainty, limitations,
and subgroup notes without global measurement or intervention identities.

The repository does not yet retrieve paper content or extract these records. Missing content,
ambiguous extraction, and absent measurements must never be silently filled in. Future validated
extractions must reference the exact document and passage supporting each result.

## Synthesize and use: future workflow

Cross-study synthesis must distinguish reported Findings from Atlas Insights, preserve contrary
and null evidence, and explain the evidence selected. Existing assessment data alone does not
establish truth or enforce complete evidence chains.

Useful outputs will render selected Insights for a purpose while retaining citations and
qualifications. No application promotion ontology or export framework is required to begin this
work. Finalized evidence must remain reproducible when future correction behavior is implemented.
