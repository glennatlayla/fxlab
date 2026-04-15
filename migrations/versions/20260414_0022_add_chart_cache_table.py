"""Add chart_cache table for caching rendered chart data.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-14

The chart_cache table stores pre-rendered or cached chart data keyed by a
composite cache key (symbol, interval, chart_type, etc.) to avoid expensive
recalculation of chart rendering on repeated requests for the same data.

Columns:
- cache_key: Unique cache identifier, indexed for fast lookup
- run_id: Deployment/run identifier, indexed for filtering cache by context
- chart_type: Type of chart (candlestick, heatmap, etc.), indexed for filtering
- data: JSON-serialized chart data payload
- created_at: Timestamp when cache entry was created
- expires_at: Timestamp when cache entry expires, indexed for cleanup queries

Indexes:
- cache_key (primary, for direct lookups)
- run_id (for filtering cache by deployment context)
- chart_type (for filtering cache by chart type)
- expires_at (for efficient cache expiration cleanup queries)

Safety implications:
- Caching reduces computational load on repeated chart rendering requests.
- Expiration index enables efficient cleanup of stale cache entries.
- run_id and chart_type indexes support efficient filtering for context-specific
  invalidation (e.g., clear all heatmaps for a given run).
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Create chart_cache table."""
    op.create_table(
        "chart_cache",
        sa.Column("cache_key", sa.String(255), primary_key=True, nullable=False),
        sa.Column("run_id", sa.String(26), nullable=False),
        sa.Column("chart_type", sa.String(100), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chart_cache_cache_key", "chart_cache", ["cache_key"])
    op.create_index("ix_chart_cache_run_id", "chart_cache", ["run_id"])
    op.create_index("ix_chart_cache_chart_type", "chart_cache", ["chart_type"])
    op.create_index("ix_chart_cache_expires_at", "chart_cache", ["expires_at"])


def downgrade() -> None:
    """Drop chart_cache table."""
    op.drop_table("chart_cache")
