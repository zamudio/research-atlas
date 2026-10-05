# Research Atlas

Research Atlas is a lightweight Python component for retrieving evidence from
open-access scholarly literature.

Given a research question, Atlas discovers relevant papers through OpenAlex,
acquires available full text, and returns ranked source passages with provenance.
It is deliberately a bounded component rather than a complete research agent.

> Research Atlas implements a bounded scholarly-evidence pipeline with explicit
> acquisition policy, typed interfaces, provenance preservation, and graceful
> partial failure.

**Discovery is not evidence. Atlas only returns evidence from scholarly full text
it successfully acquired and prepared.**

```text
question
   │
   ▼
OpenAlex discovery
   │
   ▼
readable-source qualification
   │
   ▼
full-text acquisition
   │
   ▼
document preparation
   │
   ▼
passage ranking
   │
   ▼
structured evidence
```

## Quick start

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/). From this checkout:

```sh
uv sync --locked
export RESEARCH_ATLAS_OPENALEX_API_KEY="YOUR_KEY"
uv run atlas evidence "Does spending time outside reduce stress?" --max-papers 3
```

In PowerShell, set the key with
`$env:RESEARCH_ATLAS_OPENALEX_API_KEY = "YOUR_KEY"`.

Atlas requires an [OpenAlex API key](https://openalex.org/settings/api) for its
cached-content routes. [OpenAlex content downloads](https://help.openalex.org/data/works/attributes/)
use the account's API budget. The only optional setting is
`RESEARCH_ATLAS_HTTP_TIMEOUT_SECONDS` (default 20, greater than 0 and at most 120).
Set environment variables directly; Atlas does not automatically load `.env`.

The same workflow is available in Python:

```python
from research_atlas import evidence

# Inside an async function:
result = await evidence(
    "Does spending time outside reduce stress?",
    max_papers=3,
)
print(result.model_dump_json(indent=2))
```

Applications can pass `settings=Settings(...)` from `research_atlas.config`
instead of using environment variables. No model service is needed.

## Result contract

The CLI writes JSON to stdout. This illustrative result uses fictional paper
metadata and passage text; it is not a research finding:

```json
{
  "question": "Does spending time outside reduce stress?",
  "papers": [
    {
      "work": {
        "openalex_id": "W123",
        "title": "Example outdoor exposure study",
        "doi": null,
        "year": 2024
      },
      "source": {
        "kind": "grobid_xml",
        "url": "https://content.openalex.org/works/W123.grobid-xml"
      },
      "evidence": [
        {
          "passage_id": "p0002",
          "section": "Results",
          "text": "Participants reported lower stress after spending time outside in a park.",
          "score": 1.42
        }
      ]
    }
  ],
  "failures": [
    {
      "openalex_id": "W456",
      "stage": "acquisition",
      "reason": "No advertised full-text route succeeded."
    }
  ]
}
```

`EvidenceResult` and its nested records are typed Pydantic models. A paper carries
its identity once and records the successful source kind and final download URL.
Evidence contains exact prepared passage text; ranking never edits that text.
**Scores measure lexical retrieval relevance only**, not scientific confidence,
effect strength, or evidence quality. Scores are calculated within each paper and
should not be compared across papers.

## Pipeline policy

- **Discovery:** one OpenAlex `search.semantic` request uses the original question,
  with `has_fulltext:true` and only needed metadata. Atlas inspects at most
  [50 results](https://help.openalex.org/api/semantic-search/), preserving provider
  order and removing duplicate work IDs. A DOI, abstract, or landing page alone
  never qualifies a work. There are no individual metadata refetches.
- **Acquisition:** cached GROBID XML → advertised public OA PDF URLs → cached PDF.
  Within OA PDFs, the best OA location comes first, then the primary location,
  then remaining locations in response order, with duplicate URLs removed.
  Each route must download **and prepare** successfully; otherwise Atlas tries
  the next. Only advertised routes are tried, sequentially, without retries.
  OpenAlex credentials are sent in headers only to OpenAlex.
- **Preparation:** XML body paragraphs retain section headings when available;
  header abstracts and bibliography metadata are excluded. PDF text uses parser
  page order with `section: null`; there is no OCR or layout reconstruction.
  Whitespace is collapsed and long blocks split at word boundaries near 2,000
  characters, without changing words, punctuation, or hyphenation. Passage IDs
  (`p0001`, …) are stable for the same content and preparation version.
- **Ranking:** a small BM25 implementation tokenizes and case-normalizes text,
  removes common English stop words, and returns at most three positive-scoring
  passages per paper. Results descend by score; ties retain source order.
  No lexical overlap yields an empty evidence list. Synonyms and morphological
  variants can be missed; Atlas does not interpret findings.

`max_papers` (default 3, allowed 1–50) counts successfully prepared papers,
including those with no lexical match. Failed candidates do not consume this
limit. The bounded discovery pool may yield fewer papers than requested.

Malformed work metadata, unavailable content, malformed XML, unreadable PDFs,
and empty extraction produce per-paper failures; other papers continue.
A failure's stage is `preparation` if any route downloaded but none could be
prepared, otherwise `acquisition`; malformed work records use `discovery`
with a nullable ID. Ineligible works are simply skipped.

Blank questions, questions over 2,000 characters, invalid limits/configuration,
and failed discovery raise normally in Python. The CLI exits nonzero with a
diagnostic on stderr for fatal errors; completed queries, including partial or
empty results, exit zero. Documents are limited to 32 MiB, PDFs to 300 pages,
individual decoded PDF streams to 8 MiB, and extracted text to four million
characters. All processing is in memory.

## Where Atlas fits

```text
research agent
    │
    ├── web/search tools
    ├── Research Atlas → scholarly evidence
    └── other tools
```

Atlas stops at evidence retrieval. It contains no synthesis, answer generation,
LLM providers, local embeddings, research planning, agents, MCP integration,
UI, database, or background jobs. The Python and JSON contracts are the
integration boundary.

## Development

The source has nine flat modules: models, configuration, OpenAlex discovery,
acquisition, preparation, passage ranking, pipeline, CLI, and package exports.
Runtime dependencies are `httpx`, `pydantic`, and `pypdf`.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

All normal tests run offline and reject unexpected HTTP requests. Six test files
cover discovery/qualification, fallback and provenance, real PDF and GROBID
preparation, stable passage IDs, deterministic ranking, partial failure, request
validation, and the complete Python/CLI workflow.

For an optional live smoke check, run the Quick start CLI command with your key.
It uses OpenAlex's API budget and returns whatever full text is available at that
time. Repeated live queries must respect OpenAlex's semantic-search rate limit
of one request per second; Atlas does not schedule or retry requests.
