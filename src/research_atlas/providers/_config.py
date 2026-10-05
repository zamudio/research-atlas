"""Runtime model configuration validation."""

import json
from collections.abc import Mapping

import httpx
from pydantic import SecretStr

from research_atlas.config import ProviderSettings
from research_atlas.providers import ModelProviderError

# Documented hosted context windows, checked 2026-10-05. Exact identities only;
# compatible endpoints and Ollama deliberately have no inferred capacity here.
_MODEL_CONTEXT_TOKENS: dict[tuple[str, str], int] = {
    # https://developers.openai.com/api/docs/models/{model}
    ("openai", "gpt-6.1-sol"): 1_050_000,
    ("openai", "gpt-6-astra"): 1_050_000,
    ("openai", "gpt-6-sol"): 1_050_000,
    ("openai", "gpt-6-luna"): 1_050_000,
    ("openai", "gpt-5.6"): 1_050_000,
    ("openai", "gpt-5.6-sol"): 1_050_000,
    # https://platform.claude.com/docs/en/models/overview
    ("anthropic", "claude-fable-5-1"): 1_000_000,
    ("anthropic", "claude-opus-5-5"): 1_000_000,
    ("anthropic", "claude-sonnet-5-5"): 1_000_000,
    ("anthropic", "claude-haiku-4-5"): 200_000,
    # https://ai.google.dev/gemini-api/docs/models/{model}
    ("gemini", "gemini-3.8-flash"): 1_048_576,
    ("gemini", "gemini-3.1-pro-preview"): 1_048_576,
    # https://www.kimi.ai/help/kimi-api/api-troubleshooting
    ("kimi", "kimi-k3"): 1_048_576,
    # https://api-docs.deepseek.com/quick_start/pricing/
    ("deepseek", "deepseek-flash"): 1_000_000,
    ("deepseek", "deepseek-v4-pro"): 1_000_000,
    # https://openrouter.ai/{model}
    ("openrouter", "openai/gpt-6.1-sol"): 1_050_000,
    ("openrouter", "anthropic/claude-sonnet-5.5"): 1_000_000,
    ("openrouter", "google/gemini-3.1-pro-preview"): 1_048_576,
    ("openrouter", "moonshotai/kimi-k3"): 1_048_576,
}


def model_context_capacity(settings: ProviderSettings, provider: str) -> int | None:
    known = _MODEL_CONTEXT_TOKENS.get((provider, model_name(settings)))
    configured = settings.model_context_tokens
    if configured is not None:
        return min(configured, known) if known is not None else configured
    return known


def request_fits_context(
    payload: Mapping[str, object], ceiling: int | None, output_tokens: int, provider: str
) -> bool:
    """Conservatively reserve a token per serialized UTF-8 byte plus output tokens.

    Adapters without context discovery use a documented or explicitly configured ceiling.
    """
    if ceiling is None:
        raise ModelProviderError(f"{provider}_context_capacity_required")
    try:
        required = (
            len(json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")) + output_tokens
        )
    except TypeError, ValueError, UnicodeError:
        raise ModelProviderError(f"{provider}_invalid_request_material") from None
    return required <= ceiling


def model_name(settings: ProviderSettings) -> str:
    model = settings.model_name
    if model is None or not model.strip():
        raise ValueError("model must be explicitly configured")
    if len(model) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in model):
        raise ValueError("model identity must be bounded printable text")
    return model


def model_base_url(
    settings: ProviderSettings, default: str | None, *, api_key: SecretStr | None = None
) -> str:
    value = settings.model_base_url
    value = value.rstrip("/") if value else default
    if not value:
        raise ValueError("model base URL must be explicitly configured")
    try:
        url = httpx.URL(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
        ):
            raise ValueError
    except httpx.InvalidURL, ValueError:
        raise ValueError(
            "model base URL requires HTTP(S) without credentials/query/fragment"
        ) from None
    if (
        api_key is not None
        and api_key.get_secret_value().strip()
        and url.scheme == "http"
        and url.host not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("authenticated generation requires HTTPS except for loopback endpoints")
    return str(url)


def model_credential(
    key: SecretStr | None, provider: str, *, required: bool = True
) -> SecretStr | None:
    if key is None or not key.get_secret_value().strip():
        if required:
            raise ValueError(f"{provider} API key must be configured")
        return None
    return key
