# Research Atlas

Research Atlas is a lightweight tool for turning a research question into
evidence-grounded, actionable guidance from scholarly literature.

The intended flow is:
`question → scholarly search → relevant evidence → synthesis → useful answer`

> What signals should I track in a learner model to understand learning, and what
> does the research actually support?

The current core:

- Orchestrates OpenAlex semantic search → content acquisition → question-aware extraction.
- Grounds evidence in exact passages from deterministic source-text projection.
- Uses a user-selected structured model and returns an in-memory evidence review.

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

`collect_evidence` preserves the exact nonblank question (at most 2,000 characters)
and reviews up to `max_sources` usable papers sequentially (default 20; allowed
1–50). One semantic search requests up to twice that many candidates, capped at 50.
The frozen `EvidenceReview.reviewed_sources` counts usable papers assessed even
when they yielded no relevant evidence; `sources` contains only evidence-bearing
`SourceEvidence` objects in search order. Evidence includes summaries, exact
projected passages, context, and limitations, with the source and input XML checksum.

Missing, unusable, or oversized content is skipped. Other OpenAlex errors expose
a safe local `OpenAlexError.code` and propagate, as do model failures and invalid
structured output or passage references. Relevance and interpretation depend on
the selected model; passage lookup guarantees the quoted text.

Everything runs in memory. Cross-paper synthesis and an actionable final answer
are not implemented yet. A custom model only needs an async
`generate(instructions, input_text, schema) -> bytes` method.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

All tests run offline.
