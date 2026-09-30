# Metadata dry-run CLI

The CLI exercises supported discovery operations without persisting a ResearchRun or processing
paper content. Run 001 remains UNEXECUTED.

```shell
uv run research-atlas-dry-run "urban heat mitigation" --limit 8 --batches 2
uv run research-atlas-dry-run "urban heat mitigation" --limit 5 --openalex-semantic "How does urban heat affect health?"
uv run research-atlas-dry-run "urban heat mitigation" --limit 5 --crossref-bibliographic "urban heat mitigation systematic review"
```

The positional query selects openalex.search. Optional flags add openalex.semantic and crossref.works
with their exact supplied queries. --limit is records per batch (1-10 for this diagnostic); --batches
is maximum batches per operation (1-10, default 1). Semantic search always returns a single bounded
set. A lexical search with a continuation at the budget boundary is explicitly partial.

JSON includes exact inputs/budgets, provider outcomes and retry checkpoints, resolved Sources,
whole metadata observations with observation IDs/credits, selected display observation IDs,
ranked memberships, and identity conflicts. Conflicted observations have null resolved Source IDs.
This is diagnostic JSON, not an export contract. Checkpoints are opaque adapter data: applications
can resume via LiteratureSearchRequest with the same query and checkpoint; the CLI does not save
or resume durable execution state.

--output tmp/dry-run.json writes an optional copy. All-operation failure emits JSON stdout, safe
explanation on stderr and exit code 1. Partial or conflict-bearing reports retain usable data and
exit 0; consumers must inspect their explicit statuses/conflict list before claiming completeness.

Configuration remains RESEARCH_ATLAS_OPENALEX_API_KEY and optional RESEARCH_ATLAS_CROSSREF_MAILTO.
See [provider semantics](providers.md) and [architecture](architecture.md).
