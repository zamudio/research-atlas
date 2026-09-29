# Metadata dry-run CLI

The CLI is a small developer diagnostic. It searches and reconciles metadata without creating a
ResearchRun, retrieving paper content, extracting evidence, or invoking an LLM. Run 001 remains
unexecuted.

```shell
uv run research-atlas-dry-run "urban heat mitigation" --limit 8
uv run research-atlas-dry-run "urban heat mitigation" --limit 5 --openalex-semantic "How does urban heat affect health?"
uv run research-atlas-dry-run "urban heat mitigation" --limit 5 --crossref-bibliographic "urban heat mitigation systematic review"
```

The positional query selects `openalex.search`. Optional flags add `openalex.semantic` and
`crossref.works` with their exact supplied queries. Limits apply per operation; query syntax is
not portable between providers. The diagnostic restricts limits to 1-10 results per operation.

JSON stdout includes requested searches, provider outcomes, reconciled Sources, and the original
metadata observations with ordered credits. Each observation retains its provider publication
provenance and references the reconciled Source ID. This is diagnostic JSON, not a versioned
research export contract. Temporary search memberships remain in the application report.

Use `--output tmp/dry-run.json` for an optional copy. If every operation fails, stdout still contains
a JSON report, stderr explains the failure, and the exit code is nonzero. A successful empty
operation is reported as such.

Configuration is limited to `RESEARCH_ATLAS_OPENALEX_API_KEY` and optional
`RESEARCH_ATLAS_CROSSREF_MAILTO`. See [provider limitations](providers.md) before interpreting results.
