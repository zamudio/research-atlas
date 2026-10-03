# Research Atlas

Research Atlas is a lightweight tool for turning a research question into
evidence-grounded, actionable guidance from scholarly literature.

The intended flow is:
`question → scholarly search → relevant evidence → synthesis → useful answer`

> What signals should I track in a learner model to understand learning, and what
> does the research actually support?

The current core:

- Searches scholarly literature with OpenAlex, including semantic search.
- Retrieves usable cached GROBID XML content.
- Extracts evidence specifically relevant to the supplied question.
- Grounds evidence in exact passages from deterministic source-text projection.
- Uses a user-selected structured model and returns paper-level evidence to callers.

## Setup

Install Python 3.14 and uv, then run `uv sync --locked`. Copy `.env.example` to
`.env` and configure an OpenAlex key for content acquisition. Select a model and
provider explicitly: Ollama, OpenAI, Anthropic, Gemini, Kimi, OpenRouter, DeepSeek,
or an OpenAI-compatible endpoint. Cloud providers need their corresponding key;
local endpoints can run without credentials. Authenticated endpoints require HTTPS
except on loopback. Set `RESEARCH_ATLAS_MODEL_BASE_URL` for a compatible endpoint.

## Current API

```python
from research_atlas import extract_evidence
from research_atlas.config import ProviderSettings
from research_atlas.openalex import OpenAlex
from research_atlas.providers.factory import create_structured_model

settings = ProviderSettings()
literature = OpenAlex(settings.openalex_api_key)
model = create_structured_model(settings)

# Inside an async function:
sources = await literature.search("learner model response time", limit=10)
if sources:
    source = sources[0]
    content = await literature.fetch_content(source)
    if content is not None:
        result = await extract_evidence(
            question="What does response time tell us about learning?",
            source=source,
            content=content,
            model=model,
        )
```

`search` returns a tuple of `Source` objects (up to 200 results; 50 with
`semantic=True`). `fetch_content` returns XML bytes, or `None` for unavailable
content; other failures raise `OpenAlexError` with a safe local code.
`extract_evidence` accepts a nonblank question of at most 8,000 characters and
returns frozen `SourceEvidence`: the source, SHA-256 of the input XML, and evidence
containing summaries, exact projected passages, context, and limitations. An
irrelevant paper can return an empty evidence tuple. Invalid structured output or
passage references raise validation errors. Relevance and interpretation depend
on the selected model; passage lookup guarantees the quoted text.

Everything runs in memory. Whole-review orchestration and cross-paper synthesis
are not implemented. A custom model only needs an async
`generate(instructions, input_text, schema) -> bytes` method.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

All tests run offline.
