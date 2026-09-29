"""Lightweight research requests, separate from actual execution records."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResearchRequest(BaseModel):
    """A user's question with optional context for planning and useful outputs.

    Plan entries are intentions, not approved future executions. Exact searches
    belong to SearchExecution; loading a request does not execute research.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1)
    research_questions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    plan: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load optional project-owned request data without creating a run."""

        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
