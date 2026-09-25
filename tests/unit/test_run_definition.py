from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.run_definition import RunDefinition

PROJECT_ROOT = Path(__file__).parents[2]
RUN_DEFINITION_PATH = (
    PROJECT_ROOT / "projects" / "ai-tutor" / "runs" / "learning-foundations-001.yaml"
)


def test_planned_run_definition_yaml_validates_without_exact_queries() -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)

    assert definition.schema_version == "0.2"
    assert definition.records_schema_version == "0.5"
    assert definition.definition_status == "planned"
    assert definition.run_id == "learning-foundations-001"
    assert all(not spec.execution_ready for spec in definition.search_plan.search_specs)
    assert all(spec.exact_query is None for spec in definition.search_plan.search_specs)
    assert all(spec.requested_limit is None for spec in definition.search_plan.search_specs)
    assert not hasattr(definition, "execution_started")


def test_run_definition_fingerprint_is_deterministic_and_content_sensitive() -> None:
    first = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    second = RunDefinition.model_validate(first.model_dump(mode="json"))

    assert first.fingerprint() == second.fingerprint()
    changed = first.model_copy(update={"label": "Changed label"})
    assert changed.fingerprint() != first.fingerprint()
    assert len(first.fingerprint()) == 64


def test_exact_query_text_is_preserved_byte_for_character() -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    payload = definition.model_dump(mode="json")
    query = 'title.search:("learning science")  AND  review\n'
    payload["search_plan"]["search_specs"][0].update(
        {
            "execution_ready": True,
            "provider_id": "openalex",
            "operation_id": "openalex.search",
            "exact_query": query,
            "requested_limit": 20,
        }
    )

    parsed = RunDefinition.model_validate(payload)

    assert parsed.search_plan.search_specs[0].exact_query == query


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", "   "),
        ("operation_id", "\t"),
        ("exact_query", " \r\n "),
    ),
)
def test_execution_ready_search_spec_rejects_blank_required_values(field: str, value: str) -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    payload = definition.model_dump(mode="json")
    spec = payload["search_plan"]["search_specs"][0]
    spec.update(
        {
            "execution_ready": True,
            "provider_id": "openalex",
            "operation_id": "openalex.search",
            "exact_query": "query",
            "requested_limit": 20,
            field: value,
        }
    )

    with pytest.raises(ValidationError, match="non-blank provider_id"):
        RunDefinition.model_validate(payload)


def test_execution_ready_search_spec_requires_requested_limit() -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    payload = definition.model_dump(mode="json")
    payload["search_plan"]["search_specs"][0].update(
        {
            "execution_ready": True,
            "provider_id": "openalex",
            "operation_id": "openalex.search",
            "exact_query": "query",
        }
    )

    with pytest.raises(ValidationError, match="require a requested_limit"):
        RunDefinition.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    (("schema_version", "0.3"), ("records_schema_version", "0.6")),
)
def test_run_definition_rejects_unsupported_schema_versions(field: str, value: str) -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    payload = definition.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        RunDefinition.model_validate(payload)


def test_approved_definition_rejects_unapproved_search_specs() -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)
    payload = definition.model_dump(mode="json")
    payload["definition_status"] = "approved"

    with pytest.raises(ValidationError, match="execution-ready search specs"):
        RunDefinition.model_validate(payload)


def test_project_run_has_extensible_protocol_references() -> None:
    definition = RunDefinition.from_yaml(RUN_DEFINITION_PATH)

    assert {reference.protocol_id for reference in definition.protocol_references} == {
        "extraction",
        "screening",
        "evidence-assessment",
    }
    assert "architecture-promotion" not in {
        reference.protocol_id for reference in definition.protocol_references
    }
