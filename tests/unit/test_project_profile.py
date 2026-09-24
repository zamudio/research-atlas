from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.project_profile import ProjectProfile


def test_ai_tutor_template_parses() -> None:
    profile = ProjectProfile.from_yaml(Path("templates/ai_tutor_learning_foundations.yaml"))

    assert profile.project_id == "ai-tutor"
    assert "persistent state" in profile.architecture_targets
    assert any("observation from inference" in item for item in profile.constraints_and_principles)


def test_project_profile_requires_version_and_provenance_context() -> None:
    with pytest.raises(ValidationError):
        ProjectProfile.model_validate(
            {
                "project_id": "consumer",
                "product_name": "Consumer",
                "research_domain": "testing",
                "objectives": ["Learn"],
                "constraints_and_principles": ["Be explicit"],
            }
        )
