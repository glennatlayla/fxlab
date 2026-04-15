"""Add signals and signal_evaluations tables (Phase 8 M3).

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-13 16:00:00.000000
"""

from typing import Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create signals and signal_evaluations tables."""
    op.create_table(
        "signals",
        sa.Column("id", sa.String(255), primary_key=True, nullable=False),
        sa.Column("strategy_id", sa.String(255), nullable=False, index=True),
        sa.Column("deployment_id", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("signal_type", sa.String(20), nullable=False),
        sa.Column("strength", sa.String(10), nullable=False),
        sa.Column("suggested_entry", sa.String(30), nullable=True),
        sa.Column("suggested_stop", sa.String(30), nullable=True),
        sa.Column("suggested_target", sa.String(30), nullable=True),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("indicators_used", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("bar_timestamp", sa.DateTime, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False, index=True),
        sa.Column("metadata_blob", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.CheckConstraint(
            "direction IN ('long', 'short', 'flat')",
            name="chk_signals_direction",
        ),
        sa.CheckConstraint(
            "signal_type IN ('entry', 'exit', 'scale_in', 'scale_out', 'stop_adjustment')",
            name="chk_signals_type",
        ),
        sa.CheckConstraint(
            "strength IN ('strong', 'moderate', 'weak')",
            name="chk_signals_strength",
        ),
    )

    # Composite index for common query pattern
    op.create_index(
        "ix_signals_strategy_symbol_generated",
        "signals",
        ["strategy_id", "symbol", "generated_at"],
    )

    op.create_table(
        "signal_evaluations",
        sa.Column("id", sa.String(255), primary_key=True, nullable=False),
        sa.Column(
            "signal_id",
            sa.String(255),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("risk_gate_results", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("position_size", sa.String(30), nullable=True),
        sa.Column("adjusted_stop", sa.String(30), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("evaluated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    """Drop signal_evaluations and signals tables."""
    op.drop_table("signal_evaluations")
    op.drop_index("ix_signals_strategy_symbol_generated", table_name="signals")
    op.drop_table("signals")
