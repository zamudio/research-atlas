from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.config import ProviderSettings
from research_atlas.providers._config import model_context_capacity


@pytest.mark.parametrize(
    "value,expected", [("", None), ("1", 1), ("4096", 4096), ("999999999", 999999999)]
)
def test_model_context_tokens_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: int | None
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_MODEL_CONTEXT_TOKENS", value)
    assert ProviderSettings().model_context_tokens == expected


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "4096.0", "true", "invalid", " "])
def test_model_context_tokens_invalid_environment(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("RESEARCH_ATLAS_MODEL_CONTEXT_TOKENS", value)
    with pytest.raises(ValidationError):
        ProviderSettings()


@pytest.mark.parametrize("value", [0, -1, True, 4096.0, 1.5])
def test_model_context_tokens_require_positive_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        ProviderSettings.model_validate({"model_context_tokens": value})


def test_model_context_tokens_absent_and_blank_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RESEARCH_ATLAS_MODEL_CONTEXT_TOKENS", raising=False)
    assert ProviderSettings().model_context_tokens is None
    dotenv = tmp_path / ".env"
    dotenv.write_text("RESEARCH_ATLAS_MODEL_CONTEXT_TOKENS=\n", encoding="utf-8")
    assert ProviderSettings().model_context_tokens is None


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("openai", "gpt-6.1-sol", 1_050_000),
        ("openai", "gpt-6-astra", 1_050_000),
        ("openai", "gpt-6-sol", 1_050_000),
        ("openai", "gpt-6-luna", 1_050_000),
        ("openai", "gpt-5.6", 1_050_000),
        ("openai", "gpt-5.6-sol", 1_050_000),
        ("anthropic", "claude-sonnet-5-5", 1_000_000),
        ("anthropic", "claude-haiku-4-5", 200_000),
        ("gemini", "gemini-3.8-flash", 1_048_576),
        ("gemini", "gemini-3.1-pro-preview", 1_048_576),
        ("kimi", "kimi-k3", 1_048_576),
        ("deepseek", "deepseek-flash", 1_000_000),
        ("deepseek", "deepseek-v4-pro", 1_000_000),
        ("openrouter", "anthropic/claude-sonnet-5.5", 1_000_000),
        ("openrouter", "moonshotai/kimi-k3", 1_048_576),
    ],
)
def test_known_model_context_capacity_and_configured_ceiling(
    provider: str, model: str, expected: int
) -> None:
    settings = ProviderSettings(model_provider=provider, model_name=model)
    assert model_context_capacity(settings, provider) == expected
    assert (
        model_context_capacity(settings.model_copy(update={"model_context_tokens": 100}), provider)
        == 100
    )
    assert (
        model_context_capacity(
            settings.model_copy(update={"model_context_tokens": expected + 1}), provider
        )
        == expected
    )


@pytest.mark.parametrize("provider", ["openai", "openrouter", "openai_compatible", "ollama"])
def test_unknown_context_capacity_never_inferred_from_a_model_name(provider: str) -> None:
    settings = ProviderSettings(model_name="gpt-6.1-sol" if provider != "openai" else "custom")
    assert model_context_capacity(settings, provider) is None
    assert (
        model_context_capacity(
            settings.model_copy(update={"model_context_tokens": 12345}), provider
        )
        == 12345
    )
