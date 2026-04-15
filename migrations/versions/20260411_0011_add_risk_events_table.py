"""Add risk_events table for durable risk check audit trail.

Creates the risk_events table for persisting pre-trade risk check results.
Previously, risk events existed only as Pydantic value objects in memory.
This migration adds SQL persistence to satisfy §0 Rule 2 (no deferred
persistence) and Phase 5 Finding F-02.

Columns:
- id: ULID primary key (String(26)).
- deployment_id: FK to deployments.id (RESTRICT).
- order_id: FK to orders.id (SET NULL, nullable — some risk events are not
  order-specific).
- check_name: Name of the risk check performed.
- passed: Boolean result of the check.
- severity: Severity level (info, warning, critical, halt).
- reason: Human-readable reason for failure (nullable if passed).
- current_value: The current value that was checked (decimal string).
- limit_value: The limit value compared against (decimal string).
- order_client_id: Client order ID that triggered the check (nullable).
- symbol: Symbol involved in the check (nullable).
- correlation_id: Distributed tracing ID (nullable).
- created_at: Timestamp when the event was recorded.

Indexes:
- deployment_id: Primary query pattern for deployment-level event listing.
- severity: Filter by severity level.
- created_at: Time-range queries and ordering.
- correlation_id: Distributed tracing lookups.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create risk_events table."""
    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column(
            "deployment_id",
            sa.String(26),
            sa.ForeignKey("deployments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.String(26),
            sa.ForeignKey("orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_name", sa.String(100), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("current_value", sa.String(50), nullable=True),
        sa.Column("limit_value", sa.String(50), nullable=True),
        sa.Column("order_client_id", sa.String(255), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical', 'halt')",
            name="chk_risk_events_severity",
        ),
    )

    # Indexes for primary query patterns.
    op.create_index("ix_risk_events_deployment_id", "risk_events", ["deployment_id"])
    op.create_index("ix_risk_events_severity", "risk_events", ["severity"])
    op.create_index("ix_risk_events_created_at", "risk_events", ["created_at"])
    op.create_index("ix_risk_events_correlation_id", "risk_events", ["correlation_id"])


def downgrade() -> None:
    """Drop risk_events table."""
    op.drop_index("ix_risk_events_correlation_id", table_name="risk_events")
    op.drop_index("ix_risk_events_created_at", table_name="risk_events")
    op.drop_index("ix_risk_events_severity", table_name="risk_events")
    op.drop_index("ix_risk_events_deployment_id", table_name="risk_events")
    op.drop_table("risk_events")
