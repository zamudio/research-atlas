from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.project_profile import ProjectProfile


def test_project_profile_yaml_parses(tmp_path: Path) -> None:
    profile_path = tmp_path / "project.yaml"
    profile_path.write_text(
        """
schema_version: "0.1"
project_id: "example-project"
product_name: "Example Product"
research_domain: "example research domain"
objectives:
  - "Understand the evidence landscape."
architecture_targets:
  - "project-supplied-destination"
constraints_and_principles:
  - "Keep observations distinct from inferences."
""".lstrip(),
        encoding="utf-8",
    )

    profile = ProjectProfile.from_yaml(profile_path)

    assert profile.project_id == "example-project"
    assert profile.architecture_targets == ("project-supplied-destination",)
    assert any("observations distinct" in item for item in profile.constraints_and_principles)


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
