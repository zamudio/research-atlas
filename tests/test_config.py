from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.config import ProviderSettings


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
