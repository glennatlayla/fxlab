"""Add data_anomalies and quality_scores tables for data quality monitoring.

Phase 8 M0: Data Quality Contracts, Interfaces & Storage Schema.

The data_anomalies table stores detected market data anomalies (OHLCV violations,
price spikes, volume anomalies, timestamp gaps, duplicates, missing bars, stale data)
for audit trail and trend analysis.

The quality_scores table stores composite quality scores per (symbol, interval) with
a unique constraint on (symbol, interval, window_start) to support idempotent upsert
and efficient latest-score lookups.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-13
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Create data_anomalies and quality_scores tables."""

    # -- data_anomalies table --
    op.create_table(
        "data_anomalies",
        sa.Column("id", sa.String(255), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("anomaly_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("detected_at", sa.DateTime, nullable=False, index=True),
        sa.Column("bar_timestamp", sa.DateTime, nullable=True),
        sa.Column("details", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')",
            name="chk_data_anomalies_severity",
        ),
        sa.CheckConstraint(
            "anomaly_type IN ('missing_bar', 'stale_data', 'ohlcv_violation', "
            "'price_spike', 'volume_anomaly', 'timestamp_gap', 'duplicate_bar')",
            name="chk_data_anomalies_type",
        ),
    )

    # Composite index for the most common query pattern:
    # find anomalies by symbol + interval + time range
    op.create_index(
        "ix_data_anomalies_symbol_interval_detected",
        "data_anomalies",
        ["symbol", "interval", "detected_at"],
    )

    # -- quality_scores table --
    op.create_table(
        "quality_scores",
        sa.Column("id", sa.String(255), primary_key=True, nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("window_start", sa.DateTime, nullable=False, index=True),
        sa.Column("window_end", sa.DateTime, nullable=False),
        sa.Column("completeness", sa.String(20), nullable=False),
        sa.Column("timeliness", sa.String(20), nullable=False),
        sa.Column("consistency", sa.String(20), nullable=False),
        sa.Column("accuracy", sa.String(20), nullable=False),
        sa.Column("composite_score", sa.String(20), nullable=False),
        sa.Column("grade", sa.String(1), nullable=False),
        sa.Column("anomaly_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "scored_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "symbol",
            "interval",
            "window_start",
            name="uq_quality_scores_symbol_interval_window",
        ),
        sa.CheckConstraint(
            "grade IN ('A', 'B', 'C', 'D', 'F')",
            name="chk_quality_scores_grade",
        ),
    )

    # Composite index for latest-score lookup
    op.create_index(
        "ix_quality_scores_symbol_interval_window",
        "quality_scores",
        ["symbol", "interval", "window_start"],
    )


def downgrade() -> None:
    """Drop data_anomalies and quality_scores tables."""
    op.drop_table("quality_scores")
    op.drop_table("data_anomalies")
