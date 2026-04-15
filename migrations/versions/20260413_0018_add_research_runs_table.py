"""
Add research_runs table for Phase 9 research pipeline.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the research_runs table."""
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("run_type", sa.String(50), nullable=False),
        sa.Column("strategy_id", sa.String(26), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("summary_metrics", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "run_type IN ('backtest', 'walk_forward', 'monte_carlo', 'composite')",
            name="chk_research_runs_run_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_research_runs_status",
        ),
    )
    op.create_index("ix_research_runs_strategy_id", "research_runs", ["strategy_id"])
    op.create_index("ix_research_runs_created_by", "research_runs", ["created_by"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])


def downgrade() -> None:
    """Drop the research_runs table."""
    op.drop_index("ix_research_runs_status", table_name="research_runs")
    op.drop_index("ix_research_runs_created_by", table_name="research_runs")
    op.drop_index("ix_research_runs_strategy_id", table_name="research_runs")
    op.drop_table("research_runs")
