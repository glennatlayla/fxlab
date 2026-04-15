"""Add Phase 4 execution tables.

Creates the core execution layer tables:
- orders: Normalized broker order records with idempotency via client_order_id.
- order_fills: Individual fill events per order.
- positions: Current position state per deployment × symbol.
- execution_events: Append-only order lifecycle events for timeline replay.
- kill_switch_events: Kill switch activation/deactivation audit trail.
- reconciliation_reports: Reconciliation run results with discrepancy tracking.

All tables use ULID primary keys (String(26)), String-typed decimal columns
for precision safety, and check constraints matching the enum values in
libs/contracts/enums.py.

Indexes support the primary query patterns:
- by deployment_id (all execution queries)
- by strategy_id (strategy-level reporting)
- by symbol (instrument-level views)
- by correlation_id (distributed tracing)
- by status (order lifecycle filtering)
- by scope + target_id (kill switch lookups)

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create execution tables."""
    # -- orders --
    op.create_table(
        "orders",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("client_order_id", sa.String(255), nullable=False, unique=True),
        sa.Column("deployment_id", sa.String(26), nullable=False),
        sa.Column("strategy_id", sa.String(26), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("order_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.String(50), nullable=False),
        sa.Column("limit_price", sa.String(50), nullable=True),
        sa.Column("stop_price", sa.String(50), nullable=True),
        sa.Column("time_in_force", sa.String(10), nullable=False, server_default="day"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("broker_order_id", sa.String(255), nullable=True),
        sa.Column("submitted_at", sa.DateTime, nullable=True),
        sa.Column("filled_at", sa.DateTime, nullable=True),
        sa.Column("cancelled_at", sa.DateTime, nullable=True),
        sa.Column("average_fill_price", sa.String(50), nullable=True),
        sa.Column("filled_quantity", sa.String(50), nullable=False, server_default="0"),
        sa.Column("rejected_reason", sa.Text, nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        # Check constraints
        sa.CheckConstraint(
            "side IN ('buy', 'sell')",
            name="chk_orders_side",
        ),
        sa.CheckConstraint(
            "order_type IN ('market', 'limit', 'stop', 'stop_limit')",
            name="chk_orders_order_type",
        ),
        sa.CheckConstraint(
            "time_in_force IN ('day', 'gtc', 'ioc', 'fok')",
            name="chk_orders_time_in_force",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'partial_fill', 'filled', "
            "'cancelled', 'rejected', 'expired')",
            name="chk_orders_status",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('shadow', 'paper', 'live')",
            name="chk_orders_execution_mode",
        ),
        # Foreign keys
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_orders_client_order_id", "orders", ["client_order_id"], unique=True)
    op.create_index("ix_orders_deployment_id", "orders", ["deployment_id"])
    op.create_index("ix_orders_strategy_id", "orders", ["strategy_id"])
    op.create_index("ix_orders_symbol", "orders", ["symbol"])
    op.create_index("ix_orders_correlation_id", "orders", ["correlation_id"])
    op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])
    op.create_index("ix_orders_status", "orders", ["status"])

    # -- order_fills --
    op.create_table(
        "order_fills",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("order_id", sa.String(26), nullable=False),
        sa.Column("fill_id", sa.String(255), nullable=False),
        sa.Column("price", sa.String(50), nullable=False),
        sa.Column("quantity", sa.String(50), nullable=False),
        sa.Column("commission", sa.String(50), nullable=False, server_default="0"),
        sa.Column("filled_at", sa.DateTime, nullable=False),
        sa.Column("broker_execution_id", sa.String(255), nullable=True),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_order_fills_order_id", "order_fills", ["order_id"])
    op.create_index("ix_order_fills_correlation_id", "order_fills", ["correlation_id"])

    # -- positions --
    op.create_table(
        "positions",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("deployment_id", sa.String(26), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("quantity", sa.String(50), nullable=False, server_default="0"),
        sa.Column("average_entry_price", sa.String(50), nullable=False, server_default="0"),
        sa.Column("market_price", sa.String(50), nullable=False, server_default="0"),
        sa.Column("market_value", sa.String(50), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", sa.String(50), nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.String(50), nullable=False, server_default="0"),
        sa.Column("cost_basis", sa.String(50), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_positions_deployment_id", "positions", ["deployment_id"])
    op.create_index("ix_positions_symbol", "positions", ["symbol"])

    # -- execution_events --
    op.create_table(
        "execution_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("order_id", sa.String(26), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("details", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_execution_events_order_id", "execution_events", ["order_id"])
    op.create_index("ix_execution_events_event_type", "execution_events", ["event_type"])
    op.create_index("ix_execution_events_correlation_id", "execution_events", ["correlation_id"])

    # -- kill_switch_events --
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(255), nullable=False),
        sa.Column("activated_by", sa.String(255), nullable=False),
        sa.Column("activated_at", sa.DateTime, nullable=False),
        sa.Column("deactivated_at", sa.DateTime, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("mtth_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "scope IN ('global', 'strategy', 'symbol')",
            name="chk_kill_switch_events_scope",
        ),
    )
    op.create_index("ix_kill_switch_events_scope", "kill_switch_events", ["scope"])
    op.create_index("ix_kill_switch_events_target_id", "kill_switch_events", ["target_id"])

    # -- reconciliation_reports --
    op.create_table(
        "reconciliation_reports",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("deployment_id", sa.String(26), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("discrepancies", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("resolved_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unresolved_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="chk_reconciliation_reports_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('startup', 'reconnect', 'scheduled', 'manual')",
            name="chk_reconciliation_reports_trigger",
        ),
        sa.ForeignKeyConstraint(["deployment_id"], ["deployments.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_reconciliation_reports_deployment_id",
        "reconciliation_reports",
        ["deployment_id"],
    )


def downgrade() -> None:
    """Drop execution tables in reverse dependency order."""
    op.drop_table("reconciliation_reports")
    op.drop_table("kill_switch_events")
    op.drop_table("execution_events")
    op.drop_table("positions")
    op.drop_table("order_fills")
    op.drop_table("orders")
