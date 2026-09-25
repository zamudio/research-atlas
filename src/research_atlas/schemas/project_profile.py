"""Generic project and optional evidence-application profile schemas."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Scope(BaseModel):
    """Optional population and domain bounds for a research project."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    population: tuple[str, ...] = ()
    domain: tuple[str, ...] = ()


class ProjectProfile(BaseModel):
    """Why a project conducts research, independent of consumer architecture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    project_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    research_domain: str = Field(min_length=1)
    objectives: tuple[str, ...] = Field(min_length=1)
    constraints_and_principles: tuple[str, ...] = Field(min_length=1)
    scope: Scope | None = None

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate a profile from YAML."""

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Project profile YAML must contain a mapping")
        return cls.model_validate(raw)


class EvidenceApplicationProfile(BaseModel):
    """Optional consumer destinations and constraints for applying evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    project_id: str = Field(min_length=1)
    application_name: str = Field(min_length=1)
    destinations: tuple[str, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = Field(min_length=1)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate an optional evidence application profile from YAML."""

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Evidence application profile YAML must contain a mapping")
        return cls.model_validate(raw)
