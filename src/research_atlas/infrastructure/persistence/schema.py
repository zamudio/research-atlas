"""The approved fourteen relations, using Core and restrictive evidence relationships."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData(
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
    }
)


def states(column: str, values: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN ({values})", name=column)


projects = sa.Table(
    "projects",
    metadata,
    sa.Column("project_id", sa.Text, primary_key=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("context", JSONB, nullable=False),
    sa.CheckConstraint("length(trim(project_id)) > 0", name="identity"),
)
research_runs = sa.Table(
    "research_runs",
    metadata,
    sa.Column("run_id", sa.Text, primary_key=True),
    sa.Column(
        "project_id",
        sa.Text,
        sa.ForeignKey("projects.project_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("request", sa.Text, nullable=False),
    sa.Column("research_questions", JSONB, nullable=False),
    sa.Column("constraints", JSONB, nullable=False),
    sa.Column("plan", JSONB, nullable=False),
    sa.Column("expected_outputs", JSONB, nullable=False),
    sa.Column("notes", JSONB, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    states("status", "'queued','running','completed','failed','cancelled'"),
    sa.CheckConstraint("length(trim(request)) > 0", name="request"),
    sa.CheckConstraint("status != 'running' OR started_at IS NOT NULL", name="started"),
    sa.CheckConstraint(
        "status NOT IN ('completed','failed','cancelled') OR completed_at IS NOT NULL",
        name="completed",
    ),
)
sa.Index("ix_research_runs_project", research_runs.c.project_id)
search_executions = sa.Table(
    "search_executions",
    metadata,
    sa.Column("search_execution_id", sa.Text, primary_key=True),
    sa.Column(
        "run_id",
        sa.Text,
        sa.ForeignKey("research_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("provider_id", sa.Text, nullable=False),
    sa.Column("operation_id", sa.Text, nullable=False),
    sa.Column("exact_query", sa.Text, nullable=False),
    sa.Column("parameters", JSONB, nullable=False),
    sa.Column("requested_limit", sa.Integer, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("provider_result_count", sa.Integer, nullable=False, server_default="0"),
    sa.Column("completed_batches", sa.Integer, nullable=False, server_default="0"),
    sa.Column("checkpoint", sa.Text),
    sa.Column("error_type", sa.Text),
    sa.Column("error_status_code", sa.Integer),
    sa.Column("error_message", sa.Text),
    sa.Column("batch_receipts", JSONB, nullable=False, server_default="{}"),
    sa.UniqueConstraint("search_execution_id", "run_id"),
    states("status", "'running','succeeded','partial','failed','cancelled'"),
    sa.CheckConstraint("requested_limit BETWEEN 1 AND 100", name="limit"),
    sa.CheckConstraint("provider_result_count >= 0 AND completed_batches >= 0", name="counts"),
    sa.CheckConstraint("status = 'running' OR completed_at IS NOT NULL", name="completion"),
    sa.CheckConstraint("status != 'succeeded' OR checkpoint IS NULL", name="exhaustion"),
    sa.CheckConstraint("status != 'partial' OR checkpoint IS NOT NULL", name="partial"),
    sa.CheckConstraint("status != 'failed' OR error_type IS NOT NULL", name="failure"),
    sa.CheckConstraint(
        "jsonb_typeof(batch_receipts) = 'object' AND jsonb_typeof(parameters) = 'array'",
        name="json_shape",
    ),
)
sa.Index("ix_search_executions_progress", search_executions.c.run_id, search_executions.c.status)
sources = sa.Table(
    "sources",
    metadata,
    sa.Column("source_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("display_observation_id", UUID(as_uuid=True)),
)
source_identifiers = sa.Table(
    "source_identifiers",
    metadata,
    sa.Column("kind", sa.Text, primary_key=True),
    sa.Column("namespace", sa.Text, primary_key=True),
    sa.Column("value", sa.Text, primary_key=True),
    sa.Column(
        "source_id",
        UUID(as_uuid=True),
        sa.ForeignKey("sources.source_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    states("kind", "'external_identifier','provider_record'"),
    sa.CheckConstraint("length(trim(namespace)) > 0 AND length(trim(value)) > 0", name="nonblank"),
)
sa.Index("ix_source_identifiers_source", source_identifiers.c.source_id)
source_metadata_observations = sa.Table(
    "source_metadata_observations",
    metadata,
    sa.Column("observation_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "source_id", UUID(as_uuid=True), sa.ForeignKey("sources.source_id", ondelete="RESTRICT")
    ),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("provider_record_id", sa.Text),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("reported", JSONB, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column(
        "search_execution_id",
        sa.Text,
        sa.ForeignKey("search_executions.search_execution_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("input_batch_key", sa.Text, nullable=False),
    sa.Column("page_position", sa.Integer, nullable=False),
    sa.Column("conflict", JSONB),
    sa.UniqueConstraint("observation_id", "source_id"),
    sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="hash"),
    sa.CheckConstraint("page_position > 0 AND last_seen_at >= retrieved_at", name="position_time"),
    sa.CheckConstraint(
        "provider_record_id IS NULL OR length(trim(provider_record_id)) > 0", name="publication_id"
    ),
)
sa.Index("ix_observations_source", source_metadata_observations.c.source_id)
sa.Index(
    "uq_observation_snapshot",
    source_metadata_observations.c.provider,
    source_metadata_observations.c.provider_record_id,
    source_metadata_observations.c.content_hash,
    unique=True,
    postgresql_where=source_metadata_observations.c.provider_record_id.is_not(None),
)
sa.Index(
    "uq_observation_keyless_replay",
    source_metadata_observations.c.search_execution_id,
    source_metadata_observations.c.input_batch_key,
    source_metadata_observations.c.page_position,
    unique=True,
    postgresql_where=source_metadata_observations.c.provider_record_id.is_(None),
)
sources.append_constraint(
    sa.ForeignKeyConstraint(
        ["display_observation_id", "source_id"],
        ["source_metadata_observations.observation_id", "source_metadata_observations.source_id"],
        name="fk_sources_display_observation",
        use_alter=True,
        ondelete="RESTRICT",
    )
)
source_documents = sa.Table(
    "source_documents",
    metadata,
    sa.Column("document_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "source_id",
        UUID(as_uuid=True),
        sa.ForeignKey("sources.source_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("content_kind", sa.Text, nullable=False),
    sa.Column("retrieval_context", sa.Text, nullable=False),
    sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("content_sha256", sa.Text),
    sa.Column("source_url", sa.Text),
    sa.Column("media_type", sa.Text),
    sa.Column("content", sa.LargeBinary),
    sa.UniqueConstraint("document_id", "source_id", "status"),
    states("status", "'usable','unavailable','failed','incomplete'"),
    sa.CheckConstraint(
        "status != 'usable' OR (content IS NOT NULL AND content_sha256 IS NOT NULL)", name="usable"
    ),
    sa.CheckConstraint(
        "(content IS NULL AND content_sha256 IS NULL) OR (content IS NOT NULL AND "
        "content_sha256 = encode(sha256(content), 'hex'))",
        name="checksum",
    ),
)
sa.Index(
    "uq_document_version",
    source_documents.c.source_id,
    source_documents.c.content_kind,
    source_documents.c.content_sha256,
    unique=True,
    postgresql_where=source_documents.c.status == "usable",
)
sa.Index("ix_documents_source_time", source_documents.c.source_id, source_documents.c.retrieved_at)
extractions = sa.Table(
    "extractions",
    metadata,
    sa.Column("extraction_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "run_id",
        sa.Text,
        sa.ForeignKey("research_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("source_document_id", UUID(as_uuid=True), nullable=False),
    sa.Column("source_id", UUID(as_uuid=True), nullable=False),
    sa.Column("document_status", sa.Text, nullable=False),
    sa.Column("purpose", sa.Text, nullable=False),
    sa.Column("configuration_sha256", sa.Text, nullable=False),
    sa.Column("configuration", sa.LargeBinary, nullable=False),
    sa.Column("record_provenance", JSONB, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("validation_outcome", sa.Text, nullable=False),
    sa.Column("review_outcome", sa.Text, nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("publication_digest", sa.Text),
    sa.Column("raw_output", sa.LargeBinary),
    sa.Column("raw_output_sha256", sa.Text),
    sa.CheckConstraint(
        "(raw_output IS NULL AND raw_output_sha256 IS NULL) OR "
        "(raw_output IS NOT NULL AND raw_output_sha256 IS NOT NULL AND "
        "raw_output_sha256 = encode(sha256(raw_output), 'hex'))",
        name="raw_output",
    ),
    sa.UniqueConstraint("extraction_id", "source_id", "status"),
    sa.ForeignKeyConstraint(
        ["source_document_id", "source_id", "document_status"],
        ["source_documents.document_id", "source_documents.source_id", "source_documents.status"],
        ondelete="RESTRICT",
    ),
    states("status", "'queued','running','accepted','review_needed','failed','rejected'"),
    states("validation_outcome", "'pending','passed','failed'"),
    states("review_outcome", "'pending','accepted','rejected','not_required'"),
    sa.CheckConstraint(
        "configuration_sha256 = encode(sha256(configuration), 'hex')", name="configuration"
    ),
    sa.CheckConstraint(
        "record_provenance->>'created_in_run_id' IS NOT NULL AND "
        "record_provenance->>'created_in_run_id' = run_id",
        name="provenance",
    ),
    sa.CheckConstraint(
        "status != 'accepted' OR (document_status = 'usable' AND validation_outcome ="
        " 'passed' AND review_outcome IN ('accepted','not_required') AND "
        "publication_digest IS NOT NULL)",
        name="accepted",
    ),
    sa.CheckConstraint(
        "(status IN ('queued','running') AND completed_at IS NULL) OR (status NOT IN "
        "('queued','running') AND completed_at >= started_at)",
        name="completion",
    ),
    sa.CheckConstraint("status = 'queued' OR started_at IS NOT NULL", name="start"),
    sa.CheckConstraint(
        "status IN ('queued','running') OR completed_at IS NOT NULL", name="finalized"
    ),
)
sa.Index("ix_extractions_document", extractions.c.source_document_id)
sa.Index("ix_extractions_run_status", extractions.c.run_id, extractions.c.status)
run_sources = sa.Table(
    "run_sources",
    metadata,
    sa.Column(
        "run_id",
        sa.Text,
        sa.ForeignKey("research_runs.run_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column(
        "source_id",
        UUID(as_uuid=True),
        sa.ForeignKey("sources.source_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("processing_state", sa.Text, nullable=False, server_default="discovered"),
    sa.Column("screening_decision", sa.Text),
    sa.Column("screening_detail", JSONB),
    sa.Column("scoped_screening", JSONB, nullable=False, server_default="{}"),
    sa.Column("selected_extraction_id", UUID(as_uuid=True)),
    sa.Column("selected_extraction_status", sa.Text, nullable=False, server_default="accepted"),
    sa.ForeignKeyConstraint(
        ["selected_extraction_id", "source_id", "selected_extraction_status"],
        ["extractions.extraction_id", "extractions.source_id", "extractions.status"],
        ondelete="RESTRICT",
    ),
    states(
        "processing_state", "'discovered','retrieved','extracted','excluded','unavailable','failed'"
    ),
    states("screening_decision", "'include','exclude','uncertain','defer','duplicate'"),
    sa.CheckConstraint("selected_extraction_status = 'accepted'", name="selection"),
    sa.CheckConstraint(
        "processing_state != 'extracted' OR selected_extraction_id IS NOT NULL", name="extracted"
    ),
    sa.CheckConstraint(
        "screening_decision != 'exclude' OR processing_state = 'excluded'", name="exclusion"
    ),
)
sa.Index("ix_run_sources_progress", run_sources.c.run_id, run_sources.c.processing_state)
sa.Index("ix_run_sources_screening", run_sources.c.run_id, run_sources.c.screening_decision)
source_discoveries = sa.Table(
    "source_discoveries",
    metadata,
    sa.Column("discovery_id", sa.Text, primary_key=True),
    sa.Column("search_execution_id", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("source_id", UUID(as_uuid=True), nullable=False),
    sa.Column("observation_id", UUID(as_uuid=True), nullable=False),
    sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("result_position", sa.Integer, nullable=False),
    sa.Column("provider_record_id", sa.Text),
    sa.UniqueConstraint("search_execution_id", "source_id"),
    sa.ForeignKeyConstraint(
        ["search_execution_id", "run_id"],
        ["search_executions.search_execution_id", "search_executions.run_id"],
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "source_id"],
        ["run_sources.run_id", "run_sources.source_id"],
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["observation_id", "source_id"],
        ["source_metadata_observations.observation_id", "source_metadata_observations.source_id"],
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("result_position > 0", name="rank"),
)
sa.Index("ix_discoveries_source", source_discoveries.c.source_id)
studies = sa.Table(
    "studies",
    metadata,
    sa.Column("study_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("source_id", UUID(as_uuid=True), nullable=False),
    sa.Column("extraction_id", UUID(as_uuid=True), nullable=False),
    sa.Column("extraction_status", sa.Text, nullable=False, server_default="accepted"),
    sa.Column("data", JSONB, nullable=False),
    sa.ForeignKeyConstraint(
        ["extraction_id", "source_id", "extraction_status"],
        ["extractions.extraction_id", "extractions.source_id", "extractions.status"],
        ondelete="RESTRICT",
    ),
    sa.CheckConstraint("extraction_status = 'accepted'", name="accepted"),
)
sa.Index("ix_studies_source", studies.c.source_id)
sa.Index("ix_studies_extraction", studies.c.extraction_id)
findings = sa.Table(
    "findings",
    metadata,
    sa.Column("finding_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "study_id",
        UUID(as_uuid=True),
        sa.ForeignKey("studies.study_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("anchors", JSONB, nullable=False),
    sa.Column("data", JSONB, nullable=False),
    sa.CheckConstraint(
        "jsonb_typeof(anchors) = 'array' AND jsonb_array_length(anchors) > 0", name="anchors"
    ),
)
sa.Index("ix_findings_study", findings.c.study_id)
insights = sa.Table(
    "insights",
    metadata,
    sa.Column("insight_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "run_id",
        sa.Text,
        sa.ForeignKey("research_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("claim", sa.Text, nullable=False),
    sa.Column("configuration_sha256", sa.Text, nullable=False),
    sa.Column("record_provenance", JSONB, nullable=False),
    sa.Column("qualifications", JSONB, nullable=False),
    sa.Column("uncertainty_and_limitations", JSONB, nullable=False),
    sa.Column("generalizability_notes", JSONB, nullable=False),
    sa.Column("publication_status", sa.Text, nullable=False, server_default="draft"),
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("configuration", sa.LargeBinary),
    sa.Column("publication_digest", sa.Text),
    states("publication_status", "'draft','published'"),
    sa.CheckConstraint(
        "publication_status <> 'published' OR (published_at IS NOT NULL "
        "AND configuration IS NOT NULL AND publication_digest IS NOT NULL "
        "AND publication_digest ~ '^[0-9a-f]{64}$' "
        "AND configuration_sha256 = encode(sha256(configuration), 'hex') "
        "AND record_provenance->>'created_in_run_id' IS NOT NULL "
        "AND record_provenance->>'created_in_run_id' = run_id)",
        name="published_content",
    ),
    sa.CheckConstraint(
        "length(trim(claim)) > 0 AND configuration_sha256 ~ '^[0-9a-f]{64}$'",
        name="claim_configuration",
    ),
)
sa.Index("ix_insights_run", insights.c.run_id)
insight_findings = sa.Table(
    "insight_findings",
    metadata,
    sa.Column(
        "insight_id",
        UUID(as_uuid=True),
        sa.ForeignKey("insights.insight_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column(
        "finding_id",
        UUID(as_uuid=True),
        sa.ForeignKey("findings.finding_id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    sa.Column("relationship", sa.Text, nullable=False),
    sa.Column("rationale", sa.Text, nullable=False),
    states("relationship", "'supporting','contradicting','contextual'"),
    sa.CheckConstraint("length(trim(rationale)) > 0", name="rationale"),
)
sa.Index("ix_insight_findings_finding", insight_findings.c.finding_id)
