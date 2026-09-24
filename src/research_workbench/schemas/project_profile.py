"""Consumer project research profile schema."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Scope(BaseModel):
    """Optional population and domain bounds for a research project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    age: tuple[str, ...] = ()
    population: tuple[str, ...] = ()
    domain: tuple[str, ...] = ()


class ProjectProfile(BaseModel):
    """Why research is being conducted and how outputs map to a consumer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    project_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    research_domain: str = Field(min_length=1)
    objectives: tuple[str, ...] = Field(min_length=1)
    architecture_targets: tuple[str, ...] = ()
    constraints_and_principles: tuple[str, ...] = Field(min_length=1)
    scope: Scope | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate a profile from YAML."""

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Project profile YAML must contain a mapping")
        return cls.model_validate(raw)
