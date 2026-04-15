"""Add pnl_snapshots table for daily P&L tracking.

Creates the pnl_snapshots table for persisting daily P&L snapshots per
deployment. Supports timeseries queries, equity curve rendering, drawdown
calculations, and performance attribution analysis.

Columns:
- id: ULID primary key (String(26))
- deployment_id: FK to deployments.id (RESTRICT on delete)
- snapshot_date: Date of the snapshot (Date, not DateTime)
- realized_pnl: Cumulative realized P&L (String(50) for decimal precision)
- unrealized_pnl: Unrealized P&L at snapshot time (String(50))
- commission: Cumulative commissions paid (String(50))
- fees: Cumulative exchange/regulatory fees (String(50))
- positions_count: Number of open positions at snapshot time (Integer)
- created_at: Record creation timestamp (DateTime, server_default now())
- updated_at: Record update timestamp (DateTime, server_default now())

Constraints:
- uq_pnl_snapshots_deployment_date: UNIQUE(deployment_id, snapshot_date)
  ensures at most one snapshot per deployment per day (upsert safety).

Indexes:
- ix_pnl_snapshots_deployment_id: Primary query pattern (by deployment).
- ix_pnl_snapshots_snapshot_date: Time-range queries across deployments.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create pnl_snapshots table with indexes and unique constraint."""
    op.create_table(
        "pnl_snapshots",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column(
            "deployment_id",
            sa.String(26),
            sa.ForeignKey("deployments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("realized_pnl", sa.String(50), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.String(50), nullable=False, server_default="0"),
        sa.Column("commission", sa.String(50), nullable=False, server_default="0"),
        sa.Column("fees", sa.String(50), nullable=False, server_default="0"),
        sa.Column("positions_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Indexes for common query patterns
    op.create_index(
        "ix_pnl_snapshots_deployment_id",
        "pnl_snapshots",
        ["deployment_id"],
    )
    op.create_index(
        "ix_pnl_snapshots_snapshot_date",
        "pnl_snapshots",
        ["snapshot_date"],
    )

    # Unique constraint: one snapshot per deployment per day
    op.create_unique_constraint(
        "uq_pnl_snapshots_deployment_date",
        "pnl_snapshots",
        ["deployment_id", "snapshot_date"],
    )


def downgrade() -> None:
    """Drop pnl_snapshots table and all associated indexes."""
    op.drop_constraint(
        "uq_pnl_snapshots_deployment_date",
        "pnl_snapshots",
        type_="unique",
    )
    op.drop_index("ix_pnl_snapshots_snapshot_date", table_name="pnl_snapshots")
    op.drop_index("ix_pnl_snapshots_deployment_id", table_name="pnl_snapshots")
    op.drop_table("pnl_snapshots")
