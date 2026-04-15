"""Add risk_alert_configs table for risk management alert thresholds.

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-14

The risk_alert_configs table stores per-deployment risk alert configuration
parameters used to trigger risk management alerts and actions. Each deployment
has exactly one config record (deployment_id is primary key) that controls
alert thresholds for VaR, concentration, correlation, and lookback period.

Columns:
- deployment_id: Deployment identifier, primary key (one config per deployment)
- var_threshold_pct: Value-at-Risk threshold percentage, default 5.0%
- concentration_threshold_pct: Concentration risk threshold percentage, default 30.0%
- correlation_threshold: Correlation threshold (0-1), default 0.90
- lookback_days: Lookback period in trading days for calculations, default 252
- enabled: Boolean flag to enable/disable risk alerts, default true
- updated_at: Timestamp of last configuration update

Constraints:
- deployment_id is primary key (enforces one config per deployment)

Safety implications:
- Centralized risk alert configuration per deployment enables consistent
  risk policy enforcement across all positions and trades.
- Default values provide sensible risk parameters for new deployments.
- updated_at timestamp enables audit trail of configuration changes.
- enabled flag allows quick disable/enable of risk alerts without deletion.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Create risk_alert_configs table."""
    op.create_table(
        "risk_alert_configs",
        sa.Column("deployment_id", sa.String(26), primary_key=True),
        sa.Column(
            "var_threshold_pct",
            sa.String(20),
            nullable=False,
            server_default="5.0",
        ),
        sa.Column(
            "concentration_threshold_pct",
            sa.String(20),
            nullable=False,
            server_default="30.0",
        ),
        sa.Column(
            "correlation_threshold",
            sa.String(20),
            nullable=False,
            server_default="0.90",
        ),
        sa.Column(
            "lookback_days",
            sa.Integer(),
            nullable=False,
            server_default="252",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Drop risk_alert_configs table."""
    op.drop_table("risk_alert_configs")
