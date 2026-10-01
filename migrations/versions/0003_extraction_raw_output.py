"""Retain exact structured model bytes on the existing Extraction relation."""

import sqlalchemy as sa
from alembic import op

revision = "0003_extraction_raw_output"
down_revision = "0002_insight_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extractions", sa.Column("raw_output", sa.LargeBinary(), nullable=True))
    op.add_column("extractions", sa.Column("raw_output_sha256", sa.Text(), nullable=True))
    op.create_check_constraint(
        "raw_output",
        "extractions",
        "(raw_output IS NULL AND raw_output_sha256 IS NULL) OR "
        "(raw_output IS NOT NULL AND raw_output_sha256 IS NOT NULL AND "
        "raw_output_sha256 = encode(sha256(raw_output), 'hex'))",
    )


def downgrade() -> None:
    op.drop_constraint("raw_output", "extractions", type_="check")
    op.drop_column("extractions", "raw_output_sha256")
    op.drop_column("extractions", "raw_output")
