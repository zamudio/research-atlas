"""Validated project-owned research run definitions."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from research_atlas.domain.execution import SearchParameter
from research_atlas.domain.versioning import ProtocolReference


class ResearchQuestion(BaseModel):
    """A stable question in a planned research run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class RunScope(BaseModel):
    """Project-defined boundaries for a research run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    populations: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    date_range: str | None = None
    languages: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class SearchSpec(BaseModel):
    """Stable planned search identity, separate from provider operation identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_spec_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    query_intent: str = Field(min_length=1)
    execution_ready: bool = False
    provider_id: str | None = None
    operation_id: str | None = None
    exact_query: str | None = None
    parameters: tuple[SearchParameter, ...] = ()
    requested_limit: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_execution_ready(self) -> Self:
        if self.execution_ready:
            required = {
                "provider_id": self.provider_id,
                "operation_id": self.operation_id,
                "exact_query": self.exact_query,
            }
            blank = [name for name, value in required.items() if value is None or not value.strip()]
            if blank:
                raise ValueError(
                    "execution-ready search specs require non-blank provider_id, operation_id, "
                    "and exact_query"
                )
            if self.requested_limit is None:
                raise ValueError("execution-ready search specs require a requested_limit")
            if any(
                not parameter.name.strip() or not parameter.value.strip()
                for parameter in self.parameters
            ):
                raise ValueError(
                    "execution-ready search parameters require non-blank names and values"
                )
        return self


class SearchPlan(BaseModel):
    """Search strategy plus stable logical search specifications."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: str = Field(min_length=1)
    search_specs: tuple[SearchSpec, ...] = Field(min_length=1)
    planned_sources: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class ScreeningPlan(BaseModel):
    """Planned stages and criteria for append-only screening decisions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stages: tuple[str, ...] = Field(min_length=1)
    inclusion_criteria: tuple[str, ...] = Field(min_length=1)
    exclusion_criteria: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class StoppingRule(BaseModel):
    """A reviewable rule for ending discovery or synthesis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_type: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TaxonomyReference(BaseModel):
    """Versioned taxonomy used to organize a run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference: str = Field(min_length=1)
    version: str = Field(min_length=1)


class EvidenceStrategy(BaseModel):
    """Generic evidence priorities and synthesis intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    priorities: tuple[str, ...] = ()
    strategy: str = Field(min_length=1)


class RunDefinition(BaseModel):
    """Validated intent for a research run, without execution state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["0.2"]
    records_schema_version: Literal["0.5"]
    definition_status: Literal["planned", "approved", "retired"]
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    output_label: str | None = None
    run_type: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    research_questions: tuple[ResearchQuestion, ...] = Field(min_length=1)
    scope: RunScope
    search_plan: SearchPlan
    screening_plan: ScreeningPlan
    stopping_rule: StoppingRule
    protocol_references: tuple[ProtocolReference, ...] = Field(min_length=1)
    taxonomy: TaxonomyReference
    evidence_strategy: EvidenceStrategy
    expected_outputs: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()
    epistemic_only: bool = True
    application_boundary: str | None = None

    @model_validator(mode="after")
    def validate_stable_identities(self) -> Self:
        question_ids = [question.question_id for question in self.research_questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("research question IDs must be unique")
        search_ids = [spec.search_spec_id for spec in self.search_plan.search_specs]
        if len(search_ids) != len(set(search_ids)):
            raise ValueError("search_spec_id values must be unique")
        protocol_keys = [
            (reference.protocol_id, reference.phase) for reference in self.protocol_references
        ]
        if len(protocol_keys) != len(set(protocol_keys)):
            raise ValueError("protocol_id and phase pairs must be unique")
        if self.definition_status == "approved" and not all(
            spec.execution_ready for spec in self.search_plan.search_specs
        ):
            raise ValueError("approved run definitions require execution-ready search specs")
        if not self.epistemic_only and not self.application_boundary:
            raise ValueError("application-capable runs require an application_boundary")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and validate a project-owned YAML definition."""

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Run definition YAML must contain a mapping")
        return cls.model_validate(raw)

    def fingerprint(self) -> str:
        """Return deterministic SHA-256 over the complete validated definition."""

        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(canonical).hexdigest()
