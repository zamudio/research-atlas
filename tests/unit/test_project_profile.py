from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.project_profile import EvidenceApplicationProfile, ProjectProfile

PROJECT_ROOT = Path(__file__).parents[2]


def test_ai_tutor_project_and_evidence_application_profiles_validate() -> None:
    project_dir = PROJECT_ROOT / "projects" / "ai-tutor"

    project = ProjectProfile.from_yaml(project_dir / "project.yaml")
    application = EvidenceApplicationProfile.from_yaml(project_dir / "application.yaml")

    assert project.project_id == application.project_id == "ai-tutor"
    assert "state" in application.destinations
    assert application.application_name == "AI Tutor"
    assert project.scope is not None
    assert not hasattr(project.scope, "age")
    assert "all ages" in project.scope.population[0]


def test_generic_project_profile_needs_no_evidence_application_profile(tmp_path: Path) -> None:
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


def test_evidence_application_profile_yaml_parses(tmp_path: Path) -> None:
    profile_path = tmp_path / "application.yaml"
    profile_path.write_text(
        """
schema_version: "0.1"
project_id: "consumer"
application_name: "Example Consumer"
destinations:
  - "policy"
constraints:
  - "Do not rewrite evidence."
""".lstrip(),
        encoding="utf-8",
    )

    profile = EvidenceApplicationProfile.from_yaml(profile_path)

    assert profile.destinations == ("policy",)


def test_evidence_application_profile_requires_destinations_and_constraints() -> None:
    with pytest.raises(ValidationError):
        EvidenceApplicationProfile.model_validate(
            {
                "schema_version": "0.1",
                "project_id": "consumer",
                "application_name": "Consumer",
                "destinations": [],
                "constraints": [],
            }
        )


@pytest.mark.parametrize(
    ("model", "payload", "version"),
    (
        (
            ProjectProfile,
            {
                "project_id": "generic",
                "display_name": "Generic",
                "research_domain": "generic evidence",
                "objectives": ["Review evidence."],
                "constraints_and_principles": ["Preserve provenance."],
            },
            "0.3",
        ),
        (
            EvidenceApplicationProfile,
            {
                "project_id": "consumer",
                "application_name": "Consumer",
                "destinations": ["policy"],
                "constraints": ["Preserve provenance."],
            },
            "0.2",
        ),
    ),
)
def test_profiles_reject_unsupported_schema_versions(
    model: type[ProjectProfile] | type[EvidenceApplicationProfile],
    payload: dict[str, object],
    version: str,
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"schema_version": version, **payload})


def test_generic_project_scope_rejects_age_field() -> None:
    with pytest.raises(ValidationError, match="age"):
        ProjectProfile.model_validate(
            {
                "schema_version": "0.2",
                "project_id": "generic",
                "display_name": "Generic",
                "research_domain": "generic evidence",
                "objectives": ["Review evidence."],
                "constraints_and_principles": ["Preserve provenance."],
                "scope": {"age": ["adults"]},
            }
        )
