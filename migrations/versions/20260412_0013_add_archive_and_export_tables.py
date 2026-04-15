"""Add archived_audit_events, archived_orders, and audit_export_jobs tables.

Creates the archive tables for data retention policy enforcement and the
audit export jobs table for tracking export operations.

Tables:
    archived_audit_events:
        Mirrors audit_events columns plus archived_at timestamp.
        Holds soft-deleted audit events past their retention period.

    archived_orders:
        Mirrors key orders columns plus archived_at timestamp.
        Holds soft-deleted orders past their retention period.

    audit_export_jobs:
        Tracks audit trail export job lifecycle (pending → completed/failed).
        Stores job metadata, content hash (SHA-256), byte size, and format.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create archived_audit_events, archived_orders, and audit_export_jobs tables."""

    # -- archived_audit_events --
    op.create_table(
        "archived_audit_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("actor", sa.String(255), nullable=False, index=True),
        sa.Column("action", sa.String(255), nullable=False),
        sa.Column("object_id", sa.String(26), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column(
            "archived_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_archived_audit_events_archived_at",
        "archived_audit_events",
        ["archived_at"],
    )

    # -- archived_orders --
    op.create_table(
        "archived_orders",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("client_order_id", sa.String(255), nullable=False),
        sa.Column("deployment_id", sa.String(26), nullable=False, index=True),
        sa.Column("strategy_id", sa.String(26), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("execution_mode", sa.String(20), nullable=False),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column(
            "archived_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_archived_orders_archived_at",
        "archived_orders",
        ["archived_at"],
    )

    # -- audit_export_jobs --
    op.create_table(
        "audit_export_jobs",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="pending"
        ),
        sa.Column("record_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "content_hash", sa.String(128), nullable=False, server_default=""
        ),
        sa.Column("byte_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "format", sa.String(10), nullable=False, server_default="json"
        ),
        sa.Column(
            "compressed", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "ix_audit_export_jobs_status",
        "audit_export_jobs",
        ["status"],
    )
    op.create_index(
        "ix_audit_export_jobs_created_at",
        "audit_export_jobs",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop archived_audit_events, archived_orders, and audit_export_jobs tables."""
    op.drop_table("audit_export_jobs")
    op.drop_table("archived_orders")
    op.drop_table("archived_audit_events")
