from pathlib import Path

import pytest

from research_atlas.config import ProviderSettings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests never read a user's .env or inherit their provider credentials."""
    monkeypatch.chdir(tmp_path)
    for field in ProviderSettings.model_fields:
        monkeypatch.delenv("RESEARCH_ATLAS_" + field.upper(), raising=False)
