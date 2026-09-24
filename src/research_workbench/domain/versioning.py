"""Independently versioned research protocol components."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtocolVersions:
    """Protocol component versions used by a run or export."""

    extraction: str
    evidence_assessment: str
    architecture_promotion: str
