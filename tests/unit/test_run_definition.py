from pathlib import Path

import pytest
from pydantic import ValidationError

from research_atlas.schemas.run_definition import ResearchRequest

PROJECT_ROOT = Path(__file__).parents[2]


def test_research_can_start_from_only_a_question() -> None:
    text = "  What do educators track about learners?\n"
    request = ResearchRequest(question=text)
    assert request.question == text
    assert request.plan == ()


@pytest.mark.parametrize("question", ["", " \r\n"])
def test_blank_research_question_is_rejected(question: str) -> None:
    with pytest.raises(ValidationError):
        ResearchRequest(question=question)


def test_learning_foundations_request_retains_questions_and_optional_plan() -> None:
    request = ResearchRequest.from_yaml(
        PROJECT_ROOT / "projects/ai-tutor/runs/learning-foundations-001.yaml"
    )
    assert len(request.research_questions) == 5
    assert request.plan
    assert any("null" in question for question in request.research_questions)


@pytest.mark.parametrize(
    "payload", ["- a list\n", "question: null\n", "question: valid\nunrecognized: true\n"]
)
def test_invalid_request_yaml_is_rejected(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "request.yaml"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValidationError):
        ResearchRequest.from_yaml(path)
