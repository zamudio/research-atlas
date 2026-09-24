"""Pydantic boundaries for importing and exporting trusted domain records."""

from pydantic import BaseModel, ConfigDict

from research_workbench.domain.constructs import ConstructRecord, MeasurementRecord
from research_workbench.domain.decisions import ArchitectureCandidate, ProductImplication
from research_workbench.domain.evidence import EvidenceAssessment
from research_workbench.domain.studies import InterventionRecord, ResearchRun, StudyRecord


class ResearchRecords(BaseModel):
    """A validated, serializable collection of normalized research records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    studies: tuple[StudyRecord, ...] = ()
    constructs: tuple[ConstructRecord, ...] = ()
    measurements: tuple[MeasurementRecord, ...] = ()
    interventions: tuple[InterventionRecord, ...] = ()
    evidence_assessments: tuple[EvidenceAssessment, ...] = ()
    architecture_candidates: tuple[ArchitectureCandidate, ...] = ()
    product_implications: tuple[ProductImplication, ...] = ()
    research_runs: tuple[ResearchRun, ...] = ()
