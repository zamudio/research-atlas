# CLI

The dry-run command discovers and normalizes source metadata. It does not create a `ResearchRun`,
start Run 001, extract evidence, or invoke an LLM. `--limit` applies per requested operation. Its
JSON search summaries preserve each logical query's generic parameter name/value pairs. No
`SearchExecution` or `SourceDiscovery` records are created.

```shell
uv run research-atlas-dry-run "urban heat mitigation systematic review" --limit 8
uv run research-atlas-dry-run "urban heat mitigation" --limit 8 \
  --openalex-semantic "How does urban heat mitigation affect public health?"
uv run research-atlas-dry-run "supply chain resilience" --limit 5 \
  --semantic-scholar-relevance "supply chain resilience systematic review"
uv run research-atlas-dry-run "museum conservation" --limit 5 \
  --semantic-scholar-bulk '"museum conservation" + (review | preservation)'
```

The positional query selects OpenAlex lexical/full-text discovery (`openalex.search`).
`--openalex-semantic QUERY` adds OpenAlex semantic discovery (`openalex.semantic`) to the same dry
run, preserving the semantic text exactly. Semantic discovery has a 50-result maximum and OpenAlex
limits it to one request per second. It is the preferred product-safe semantic-discovery candidate
currently being evaluated; Semantic Scholar relevance remains an optional/internal comparator.
`--semantic-scholar-relevance` selects that comparator's plain-text relevance operation, while
`--semantic-scholar-bulk` selects its Boolean/filter-oriented bulk operation. Every provider
receives the exact query supplied for that operation. Syntax is not treated as portable between
providers.

In ordinary OpenAlex lexical `search`, `?` and `*` are wildcard syntax and may be rejected unless
exact-search semantics are used. Research Atlas does not silently strip or rewrite the query to
work around this provider behavior.

These options remain metadata-only: they do not create `ResearchRun`, `SearchExecution`, or
`SourceDiscovery` records, and they do not authorize Run 001 execution.

## Experimental Crossref comparison

```shell
uv run research-atlas-dry-run "urban heat mitigation" --limit 5 \
  --crossref-bibliographic "urban heat mitigation systematic review"
```

`--crossref-bibliographic QUERY` adds `crossref.works` to the same metadata-only discovery report
alongside OpenAlex and any explicitly selected S2 operations. The exact text becomes Crossref's
`query.bibliographic`; it is bibliographic lookup, not semantic search. Results merge only by
existing exact identities. OpenAlex plus Crossref alone does not acquire S2 ownership.
Optionally set `RESEARCH_ATLAS_CROSSREF_MAILTO` to your own contact address for polite access;
no signup or paid token is required. Review small local canaries before adopting this experimental
provider permanently. See [provider details and limitations](providers.md).

## PowerShell-safe complex bulk queries

For complex native Semantic Scholar expressions on Windows PowerShell, use a UTF-8 file so the
shell and `uv run` do not reinterpret quotes or operators. The file is read with newline
preservation and its contents are sent exactly as written, including any trailing newline. Write
only the query text.

```powershell
New-Item -ItemType Directory -Force tmp | Out-Null
$bulkQueryPath = Join-Path $PWD "tmp\s2-bulk-query.txt"
$bulkQuery = '"intelligent tutoring systems" + ("meta analysis" | "systematic review")'
[IO.File]::WriteAllText($bulkQueryPath, $bulkQuery, [Text.UTF8Encoding]::new($false))
uv run research-atlas-dry-run "intelligent tutoring systems" --limit 1 `
  --semantic-scholar-bulk-file $bulkQueryPath
```

`--semantic-scholar-bulk QUERY` and `--semantic-scholar-bulk-file PATH` are mutually exclusive.

## Request diagnostics

Add `--diagnose-s2-requests` to print one secret-safe line per physical Semantic Scholar attempt to
stderr while JSON stdout remains clean:

```shell
uv run research-atlas-dry-run "supply chain resilience" --limit 5 \
  --semantic-scholar-relevance "supply chain resilience systematic review" \
  --diagnose-s2-requests
```

Each line contains the operation, endpoint path, attempt number, elapsed monotonic start, response
status, retry reason, and delay. It does not contain credentials or query text.

Use `--output tmp/dry-run.json` to save JSON. OpenAlex and Semantic Scholar keys are optional for
small calls and are loaded from `RESEARCH_ATLAS_OPENALEX_API_KEY` and
`RESEARCH_ATLAS_SEMANTIC_SCHOLAR_API_KEY`.
