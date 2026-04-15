"""Add Phase 4 deployment state machine columns and transitions table.

Extends the existing deployments table with state machine columns:
- state: 10-value deployment lifecycle state (check constraint)
- execution_mode: shadow/paper/live (check constraint)
- emergency_posture: flatten_all/cancel_open/hold/custom (check constraint)
- risk_limits: JSON risk configuration
- custom_posture_config: Optional JSON custom posture configuration

Creates the deployment_transitions table:
- Append-only audit trail for deployment state transitions
- Links to deployments via FK with CASCADE delete
- Indexed by deployment_id and correlation_id

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add state machine columns to deployments and create transitions table."""
    # -- Extend deployments table --
    op.add_column(
        "deployments",
        sa.Column("state", sa.String(30), nullable=False, server_default="created"),
    )
    op.add_column(
        "deployments",
        sa.Column("execution_mode", sa.String(10), nullable=False, server_default="paper"),
    )
    op.add_column(
        "deployments",
        sa.Column("emergency_posture", sa.String(20), nullable=False, server_default=""),
    )
    op.add_column(
        "deployments",
        sa.Column("risk_limits", sa.JSON, nullable=False, server_default="{}"),
    )
    op.add_column(
        "deployments",
        sa.Column("custom_posture_config", sa.JSON, nullable=True),
    )

    # Check constraints for new columns
    op.create_check_constraint(
        "chk_deployments_state",
        "deployments",
        "state IN ('created', 'pending_approval', 'approved', 'activating', "
        "'active', 'frozen', 'deactivating', 'deactivated', 'rolled_back', 'failed')",
    )
    op.create_check_constraint(
        "chk_deployments_execution_mode",
        "deployments",
        "execution_mode IN ('shadow', 'paper', 'live')",
    )
    op.create_check_constraint(
        "chk_deployments_emergency_posture",
        "deployments",
        "emergency_posture IN ('flatten_all', 'cancel_open', 'hold', 'custom', '')",
    )

    # Index on state for filtering
    op.create_index("ix_deployments_state", "deployments", ["state"])

    # -- Create deployment_transitions table --
    op.create_table(
        "deployment_transitions",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("deployment_id", sa.String(26), nullable=False),
        sa.Column("from_state", sa.String(30), nullable=False),
        sa.Column("to_state", sa.String(30), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("transitioned_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_deployment_transitions_deployment_id",
        "deployment_transitions",
        ["deployment_id"],
    )
    op.create_index(
        "ix_deployment_transitions_correlation_id",
        "deployment_transitions",
        ["correlation_id"],
    )


def downgrade() -> None:
    """Drop deployment transitions table and state machine columns."""
    op.drop_table("deployment_transitions")

    op.drop_index("ix_deployments_state", table_name="deployments")

    # Drop check constraints (named constraints can be dropped by name)
    op.drop_constraint("chk_deployments_emergency_posture", "deployments", type_="check")
    op.drop_constraint("chk_deployments_execution_mode", "deployments", type_="check")
    op.drop_constraint("chk_deployments_state", "deployments", type_="check")

    op.drop_column("deployments", "custom_posture_config")
    op.drop_column("deployments", "risk_limits")
    op.drop_column("deployments", "emergency_posture")
    op.drop_column("deployments", "execution_mode")
    op.drop_column("deployments", "state")
