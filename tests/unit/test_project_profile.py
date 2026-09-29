from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.project_profile import ProjectProfile


def test_project_requires_only_identity_and_display_name() -> None:
    profile = ProjectProfile(project_id="generic", display_name="A research project")
    assert profile.objectives == ()
    assert profile.scope == {}


@pytest.mark.parametrize("field", ["project_id", "display_name"])
def test_blank_project_identity_is_rejected(field: str) -> None:
    payload = {"project_id": "generic", "display_name": "Project", field: " "}
    with pytest.raises(ValidationError):
        ProjectProfile.model_validate(payload)


def test_ai_tutor_profile_keeps_optional_research_context() -> None:
    profile = ProjectProfile.from_yaml(Path(__file__).parents[2] / "projects/ai-tutor/project.yaml")
    assert profile.project_id == "ai-tutor"
    assert profile.objectives
    assert "all ages" in profile.scope["population"][0]


def test_scope_accepts_project_defined_dimensions() -> None:
    profile = ProjectProfile(
        project_id="generic", display_name="Project", scope={"setting": ("rural schools",)}
    )
    assert profile.scope["setting"] == ("rural schools",)
