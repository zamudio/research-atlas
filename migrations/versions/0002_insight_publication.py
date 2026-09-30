"""Retain exact synthesis publication and freeze historical Insight evidence.

Revision ID: 0002_insight_publication
Revises: 0001_lean_persistence
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_insight_publication"
down_revision = "0001_lean_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "insights",
        sa.Column("publication_status", sa.Text(), nullable=False, server_default="draft"),
    )
    op.add_column("insights", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("insights", sa.Column("configuration", sa.LargeBinary()))
    op.add_column("insights", sa.Column("publication_digest", sa.Text()))
    op.create_check_constraint(
        "publication_status", "insights", "publication_status IN ('draft','published')"
    )
    op.create_check_constraint(
        "published_content",
        "insights",
        "publication_status <> 'published' OR (published_at IS NOT NULL "
        "AND configuration IS NOT NULL AND publication_digest IS NOT NULL "
        "AND publication_digest ~ '^[0-9a-f]{64}$' "
        "AND configuration_sha256 = encode(sha256(configuration), 'hex') "
        "AND record_provenance->>'created_in_run_id' IS NOT NULL "
        "AND record_provenance->>'created_in_run_id' = run_id)",
    )
    op.execute("""
        CREATE FUNCTION atlas_insight_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' AND OLD.publication_status = 'published' THEN
                RAISE EXCEPTION 'published Insight is immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            IF NEW.publication_status = 'published' THEN
                IF NOT EXISTS (SELECT 1 FROM insight_findings
                               WHERE insight_id = NEW.insight_id
                               AND relationship = 'supporting') THEN
                    RAISE EXCEPTION 'published Insight requires supporting evidence';
                END IF;
                IF (SELECT count(*) FROM insight_findings
                    WHERE insight_id = NEW.insight_id) > 100 THEN
                    RAISE EXCEPTION 'Insight exceeds bounded evidence selection';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_insights BEFORE INSERT OR UPDATE OR DELETE ON insights
        FOR EACH ROW EXECUTE FUNCTION atlas_insight_immutable();

        CREATE FUNCTION atlas_insight_links_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_id uuid;
        BEGIN
            -- Parent lock serializes link changes with publication and other link changes.
            FOR parent_id IN
                SELECT insight_id FROM insights WHERE
                    (TG_OP <> 'INSERT' AND insight_id = OLD.insight_id) OR
                    (TG_OP <> 'DELETE' AND insight_id = NEW.insight_id)
                ORDER BY insight_id FOR UPDATE
            LOOP
                IF EXISTS (SELECT 1 FROM insights WHERE insight_id = parent_id
                           AND publication_status = 'published') THEN
                    RAISE EXCEPTION 'published Insight relationships are immutable';
                END IF;
            END LOOP;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER immutable_insight_findings BEFORE INSERT OR UPDATE OR DELETE
        ON insight_findings FOR EACH ROW EXECUTE FUNCTION atlas_insight_links_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER immutable_insight_findings ON insight_findings")
    op.execute("DROP FUNCTION atlas_insight_links_immutable()")
    op.execute("DROP TRIGGER immutable_insights ON insights")
    op.execute("DROP FUNCTION atlas_insight_immutable()")
    op.drop_constraint("published_content", "insights", type_="check")
    op.drop_constraint("publication_status", "insights", type_="check")
    for name in ("publication_digest", "configuration", "published_at", "publication_status"):
        op.drop_column("insights", name)
