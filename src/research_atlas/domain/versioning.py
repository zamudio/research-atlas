"""Independently versioned research protocol references."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtocolReference:
    """One protocol used in a named phase of research work."""

    protocol_id: str
    version: str
    phase: str

    def __post_init__(self) -> None:
        if not self.protocol_id or not self.version or not self.phase:
            raise ValueError("protocol_id, version, and phase must be non-empty")
