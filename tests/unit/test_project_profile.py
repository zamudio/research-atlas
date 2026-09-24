from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.project_profile import ProjectProfile, TranslationProfile

PROJECT_ROOT = Path(__file__).parents[2]


def test_ai_tutor_project_and_translation_profiles_validate() -> None:
    project_dir = PROJECT_ROOT / "projects" / "ai-tutor"

    project = ProjectProfile.from_yaml(project_dir / "project.yaml")
    translation = TranslationProfile.from_yaml(project_dir / "translation.yaml")

    assert project.project_id == translation.project_id == "ai-tutor"
    assert "state" in translation.destinations


def test_generic_project_profile_needs_no_translation_profile(tmp_path: Path) -> None:
    profile_path = tmp_path / "project.yaml"
    profile_path.write_text(
        """
schema_version: "0.2"
project_id: "scholarly-project"
display_name: "Scholarly Project"
research_domain: "example research domain"
objectives:
  - "Understand the evidence landscape."
constraints_and_principles:
  - "Keep observations distinct from inferences."
""".lstrip(),
        encoding="utf-8",
    )

    profile = ProjectProfile.from_yaml(profile_path)

    assert profile.project_id == "scholarly-project"
    assert profile.display_name == "Scholarly Project"
    assert not hasattr(profile, "architecture_targets")


def test_translation_profile_yaml_parses(tmp_path: Path) -> None:
    profile_path = tmp_path / "translation.yaml"
    profile_path.write_text(
        """
schema_version: "0.1"
project_id: "consumer"
consumer_name: "Example Consumer"
destinations:
  - "policy"
constraints:
  - "Do not rewrite evidence."
""".lstrip(),
        encoding="utf-8",
    )

    profile = TranslationProfile.from_yaml(profile_path)

    assert profile.destinations == ("policy",)


def test_translation_profile_requires_destinations_and_constraints() -> None:
    with pytest.raises(ValidationError):
        TranslationProfile.model_validate(
            {
                "schema_version": "0.1",
                "project_id": "consumer",
                "consumer_name": "Consumer",
                "destinations": [],
                "constraints": [],
            }
        )
