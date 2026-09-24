"""Tests for environment-backed provider settings."""

from pathlib import Path

from pytest import MonkeyPatch

from research_atlas.infrastructure.config import ProviderSettings


def test_provider_settings_use_research_atlas_prefix(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RESEARCH_ATLAS_OPENALEX_API_KEY", "atlas-key")

    settings = ProviderSettings()

    assert settings.openalex_api_key == "atlas-key"
