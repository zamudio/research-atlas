# Research Atlas

Research Atlas helps you find what the research actually says—and what to do with it.
Ask a question, search the scholarly literature, extract the evidence that matters, and turn it into useful guidance.

The intended experience is:
`question → scholarly search → relevant evidence → synthesis → useful answer`

## Examples

- What signals should I track in a learner model to understand learning, and what
  does the research actually support?
- How much can trees cool a city during a heat wave?
- Can concrete made with recycled materials stay strong and durable?

## Current capabilities

- Searches scholarly literature with OpenAlex and retrieves available paper content.
- Finds evidence relevant to your question and ties it to exact source passages.
- Returns your review in memory using the model you choose.

## Setup

Install Python 3.14 and uv, then run `uv sync --locked`. Copy `.env.example` to
`.env` and configure an OpenAlex key for content acquisition. Select a model and
provider explicitly: Ollama, OpenAI, Anthropic, Gemini, Kimi, OpenRouter, DeepSeek,
or an OpenAI-compatible endpoint. Cloud providers need their corresponding key;
local endpoints can run without credentials. Authenticated endpoints require HTTPS
except on loopback. Set `RESEARCH_ATLAS_MODEL_BASE_URL` for a compatible endpoint.

## Current API

```python
from research_atlas import collect_evidence
from research_atlas.config import ProviderSettings
from research_atlas.openalex import OpenAlex
from research_atlas.providers.factory import create_structured_model

settings = ProviderSettings()
literature = OpenAlex(settings.openalex_api_key)
model = create_structured_model(settings)

# Inside an async function:
review = await collect_evidence(
    "What signals should I track in a learner model to understand learning?",
    literature=literature,
    model=model,
)

print(review.reviewed_sources)
for source_result in review.sources:
    print(source_result.source.title)
    for evidence in source_result.evidence:
        print(evidence.summary)
```

### What `collect_evidence()` does

- Uses your question unchanged for semantic scholarly search. Questions
  must be nonblank and at most 2,000 characters.
- Reviews up to `max_sources` papers sequentially (default 20; allowed 1–50).
- Finds relevant evidence in each paper with available content.

### What comes back

The returned `EvidenceReview` contains:

- `question`: the original research question.
- `reviewed_sources`: the number of usable papers actually reviewed, including
  those that yielded no relevant evidence.
- `sources`: only papers that contributed evidence, in search order. Each includes
  source details and evidence summaries with exact supporting passages, context,
  and limitations.

### Availability and failures

Missing or oversized paper content is skipped. Malformed or unusable GROBID XML
raises `ValueError` during extraction. Other retrieval errors, model failures,
invalid structured output, and invalid passage references also propagate.
Relevance and interpretation depend on the model you choose; supporting passages
are exact source text.

### Current scope

Everything runs in memory. Cross-paper synthesis and an actionable final answer
are not implemented yet.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

All tests run offline.
