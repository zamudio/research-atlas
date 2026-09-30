"""One supplied synthesizer, explicit evidence, and one atomic publication."""

from datetime import datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from research_atlas.application.read_models import FindingEvidence, selected_ids
from research_atlas.domain.evidence import Insight, InsightFinding
from research_atlas.domain.provenance import RecordProvenance
from research_atlas.schemas.insight_proposal import InsightProposal


class InsightSynthesizer(Protocol):
    async def propose(self, evidence: tuple[FindingEvidence, ...], configuration: bytes) -> str:
        """Return proposal JSON; roles are explicit judgments, never inferred from direction."""
        ...


class InsightPublication(Protocol):
    async def load_evidence(
        self, run_id: str, finding_ids: tuple[UUID, ...]
    ) -> tuple[FindingEvidence, ...]: ...

    async def publish(
        self,
        insight: Insight,
        configuration: bytes,
        finding_ids: tuple[UUID, ...],
        relationships: tuple[InsightFinding, ...],
        published_at: datetime,
    ) -> None: ...


async def synthesize_insight(
    publication: InsightPublication,
    synthesizer: InsightSynthesizer,
    *,
    run_id: str,
    insight_id: UUID,
    finding_ids: tuple[UUID, ...],
    configuration: bytes,
    provenance: RecordProvenance,
    published_at: datetime,
) -> Insight:
    selected_ids(finding_ids)
    packet = await publication.load_evidence(run_id, finding_ids)
    proposal = InsightProposal.model_validate_json(await synthesizer.propose(packet, configuration))
    proposal.validate_selection(finding_ids)
    insight = Insight(
        insight_id,
        run_id,
        proposal.claim,
        sha256(configuration).hexdigest(),
        provenance,
        proposal.qualifications,
        proposal.uncertainty_and_limitations,
        proposal.generalizability_notes,
    )
    relationships = tuple(
        InsightFinding(insight_id, item.finding_id, item.relationship, item.rationale)
        for item in proposal.relationships
    )
    await publication.publish(insight, configuration, finding_ids, relationships, published_at)
    return insight
