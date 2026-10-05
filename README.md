# Research Atlas

**Turn a research question into traceable evidence from open-access scholarly full text.**

Research Atlas is a small Python package for retrieving relevant passages from scholarly papers. It uses OpenAlex to discover readable works, acquires available full text, prepares the documents, and returns ranked passages with source provenance.

It is designed to be a focused component inside scripts, research tools, and AI systems—not a complete research agent.

```text
question
   │
   ▼
OpenAlex discovery
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

## Where Atlas fits

```text
research agent / application
        │
        ├── web search
        ├── code / data tools
        ├── Research Atlas ──→ scholarly evidence
        └── other tools
```

Atlas owns the scholarly-evidence step. The surrounding application can decide how to interpret, compare, synthesize, or present that evidence.

## Quick start

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
export RESEARCH_ATLAS_OPENALEX_API_KEY="YOUR_KEY"

uv run atlas evidence \
  "Does spending time outside reduce stress?" \
  --max-papers 3
```

In PowerShell:

```powershell
$env:RESEARCH_ATLAS_OPENALEX_API_KEY = "YOUR_KEY"

uv run atlas evidence `
  "Does spending time outside reduce stress?" `
  --max-papers 3
```

Atlas requires an [OpenAlex API key](https://openalex.org/settings/api) for cached full-text content.

The same workflow is available from Python:

```python
from research_atlas import evidence

result = await evidence(
    "Does spending time outside reduce stress?",
    max_papers=3,
)

print(result.model_dump_json(indent=2))
```

No model service, embedding model, or vector database is required.

## Result contract

Atlas returns structured evidence rather than a synthesized answer.

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

The example above uses fictional metadata and text.

Each successful paper records:

- scholarly identity;
- the full-text source that actually succeeded;
- exact prepared source passages;
- section information when available;
- a lexical retrieval score.

Scores indicate **passage relevance to the query only**. They are not measures of scientific confidence, evidence quality, or effect strength.

Failures are reported per paper so one unavailable or malformed source does not prevent useful results from other papers.

## How it works

Atlas deliberately keeps the pipeline small:

1. **Discover** — Search OpenAlex semantically using the original research question.
2. **Qualify** — Consider only works that advertise a supported full-text route.
3. **Acquire** — Try available GROBID XML and open-access PDF routes in a deterministic order.
4. **Prepare** — Convert successful full text into stable, ordered passages.
5. **Rank** — Use lightweight BM25-style lexical retrieval to select the passages most relevant to the question.
6. **Return** — Emit typed, provenance-preserving evidence and any per-paper failures.

`max_papers` counts successfully prepared papers rather than failed download attempts.

## Scope and behavior

Research Atlas is intentionally bounded.

- OpenAlex is the discovery source.
- Full-text acquisition uses advertised GROBID XML and open-access PDF routes.
- Evidence text is taken directly from prepared source content; Atlas does not rewrite it.
- Passage ranking is deterministic lexical retrieval and can miss semantic matches with little word overlap.
- XML preparation preserves section context where available; PDF extraction follows document page order.
- Individual acquisition or preparation failures are returned with the result instead of aborting the entire query.
- Fatal discovery, configuration, or request errors still fail normally.
- Processing is bounded and performed in memory.

Atlas does **not** perform synthesis, answer generation, research planning, LLM inference, embeddings, agent orchestration, MCP integration, persistence, or UI.

Its Python and JSON contracts are the integration boundary.