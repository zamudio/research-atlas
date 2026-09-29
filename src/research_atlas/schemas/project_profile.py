"""Small reusable project configuration, independent of downstream consumers."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectProfile(BaseModel):
    """Project identity with optional research context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str | None = None
    research_domain: str | None = None
    objectives: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    scope: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("project_id", "display_name")
    @classmethod
    def identity_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("project identity and display name must not be blank")
        return value

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
