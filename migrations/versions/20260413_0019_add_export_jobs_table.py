"""
Add export_jobs table for Phase 9 Track B data export jobs.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-13

Tracks asynchronous export jobs through their lifecycle:
pending → processing → complete/failed.

Includes indexes on object_id (for listing exports of a specific run/artifact),
requested_by (for user's export history), and status (for job queue queries).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the export_jobs table."""
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("export_type", sa.String(20), nullable=False),
        sa.Column("object_id", sa.String(26), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("override_watermark", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "export_type IN ('trades', 'runs', 'artifacts')",
            name="chk_export_jobs_export_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'complete', 'failed')",
            name="chk_export_jobs_status",
        ),
    )
    op.create_index("ix_export_jobs_object_id", "export_jobs", ["object_id"])
    op.create_index("ix_export_jobs_requested_by", "export_jobs", ["requested_by"])
    op.create_index("ix_export_jobs_status", "export_jobs", ["status"])


def downgrade() -> None:
    """Drop the export_jobs table."""
    op.drop_index("ix_export_jobs_status", table_name="export_jobs")
    op.drop_index("ix_export_jobs_requested_by", table_name="export_jobs")
    op.drop_index("ix_export_jobs_object_id", table_name="export_jobs")
    op.drop_table("export_jobs")
