"""Deterministic presentation of published claims; no additional synthesis."""

import re

from research_atlas.application.read_models import MAX_INSIGHTS, OutputInsight, selected_ids


def _text(value: str) -> str:
    # Keep supplied text visibly literal, including Markdown/HTML that could hide a caveat.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", " ".join(value.splitlines()))


def render_evidence_brief(
    insights: tuple[OutputInsight, ...],
    *,
    title: str,
    context: str = "",
) -> str:
    """Use reads.output_insights(engine, explicit_ids) as input. Output is never persisted."""
    selected_ids(tuple(item.detail.insight.insight_id for item in insights), MAX_INSIGHTS)
    if not title.strip():
        raise ValueError("Evidence Brief title is required")
    lines = [f"# {_text(title)}", ""]
    if context:
        lines.extend([_text(context), ""])
    for output in insights:
        detail = output.detail
        insight = detail.insight
        if detail.publication_status != "published":
            raise ValueError("Evidence Brief requires published Insights")
        evidence = sorted(output.evidence, key=lambda item: item.relationship.finding_id)
        ids = [item.relationship.finding_id for item in evidence]
        if (
            len(ids) != len(set(ids))
            or len(ids) != detail.evidence.findings
            or not any(item.relationship.relationship == "supporting" for item in evidence)
            or any(item.relationship.insight_id != insight.insight_id for item in evidence)
        ):
            raise ValueError("Evidence Brief requires complete published evidence")
        lines.extend(
            [
                f"## Insight {insight.insight_id}",
                "",
                _text(insight.claim),
                "",
                f"Run: {_text(insight.run_id)}. Published: {detail.published_at}.",
                f"Configuration SHA-256: {insight.configuration_sha256}.",
                "",
            ]
        )
        for heading, notes in (
            ("Qualifications", insight.qualifications),
            ("Uncertainty and limitations", insight.uncertainty_and_limitations),
            ("Generalizability", insight.generalizability_notes),
        ):
            lines.extend([f"### {heading}", ""])
            lines.extend(f"- {_text(note)}" for note in notes)
            if not notes:
                lines.append("None recorded.")
            lines.append("")
        counts = detail.evidence
        lines.extend(
            [
                f"Evidence: {counts.findings} Findings; {counts.studies} distinct Studies; "
                f"{counts.sources} distinct Sources. Counts do not establish independence.",
                "",
            ]
        )
        lines.extend(f"- {_text(warning)}" for warning in counts.warnings)
        lines.append("")
        for role, heading in (
            ("supporting", "Supporting evidence"),
            ("contradicting", "Contradictory evidence"),
            ("contextual", "Contextual evidence"),
        ):
            lines.extend([f"### {heading}", ""])
            matches = [item for item in evidence if item.relationship.relationship == role]
            if not matches:
                lines.extend(["None linked.", ""])
            for item in matches:
                finding, chain = item.evidence.finding, item.evidence.context
                citation = chain.source
                byline = "; ".join(credit.display_name for credit in citation.credits)
                available = [
                    part
                    for part in (
                        byline,
                        str(citation.year) if citation.year else None,
                        citation.title,
                    )
                    if part
                ]
                lines.extend(
                    [
                        f"- Finding {finding.finding_id}: {_text(finding.result_summary)}",
                        f"  Rationale: {_text(item.relationship.rationale)}",
                        f"  Direction/status: {_text(finding.direction)} / {_text(finding.status)}",
                    ]
                )
                for label, text in (
                    ("Effect estimate", finding.effect_estimate),
                    ("Uncertainty", finding.uncertainty),
                ):
                    if text:
                        lines.append(f"  {label}: {_text(text)}")
                for label, notes in (
                    ("Limitations", finding.limitations),
                    ("Moderators/subgroups", finding.moderator_and_subgroup_notes),
                ):
                    if notes:
                        lines.append(f"  {label}: " + "; ".join(_text(note) for note in notes))
                lines.extend(
                    [
                        "  Citation: "
                        + (
                            _text(". ".join(available))
                            if available
                            else "Bibliographic metadata unavailable."
                        ),
                        f"  Source {citation.source_id}; Study {chain.study.study_id}; "
                        f"Extraction {chain.extraction.extraction_id}; "
                        f"SourceDocument {chain.document.document_id}.",
                        f"  Document SHA-256: {chain.document.content_sha256}.",
                    ]
                )
                for anchor in finding.evidence_anchors:
                    if anchor.locator:
                        lines.append(f"  Locator: {_text(anchor.locator)}")
                    if anchor.passage:
                        lines.append(f"  Passage: {_text(anchor.passage)}")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"
