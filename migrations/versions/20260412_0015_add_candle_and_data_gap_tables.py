"""Add candle_records and data_gap_records tables for market data storage.

Phase 7 M0: Market Data Contracts, Interfaces & Storage Schema.

The candle_records table stores normalized OHLCV candlestick data from any
market data provider (Alpaca, Schwab, etc.) with a composite unique constraint
on (symbol, interval, timestamp) to prevent duplicate ingestion and enable
efficient bulk upsert via INSERT ... ON CONFLICT DO UPDATE.

The data_gap_records table tracks detected gaps in candle data, enabling
operators to monitor data quality and schedule backfill tasks.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-12
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Create candle_records and data_gap_records tables."""
    # -- candle_records -------------------------------------------------------
    op.create_table(
        "candle_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("open", sa.String(50), nullable=False),
        sa.Column("high", sa.String(50), nullable=False),
        sa.Column("low", sa.String(50), nullable=False),
        sa.Column("close", sa.String(50), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vwap", sa.String(50), nullable=True),
        sa.Column("trade_count", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "symbol", "interval", "timestamp",
            name="uq_candle_symbol_interval_timestamp",
        ),
    )
    op.create_index("ix_candle_records_symbol", "candle_records", ["symbol"])
    op.create_index("ix_candle_records_interval", "candle_records", ["interval"])
    op.create_index("ix_candle_records_timestamp", "candle_records", ["timestamp"])
    # Composite index for the most common query pattern: symbol + interval + time range
    op.create_index(
        "ix_candle_records_symbol_interval_timestamp",
        "candle_records",
        ["symbol", "interval", "timestamp"],
    )

    # -- data_gap_records -----------------------------------------------------
    op.create_table(
        "data_gap_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(10), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("gap_start", sa.DateTime(), nullable=False),
        sa.Column("gap_end", sa.DateTime(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_data_gap_records_symbol", "data_gap_records", ["symbol"])


def downgrade() -> None:
    """Drop candle_records and data_gap_records tables."""
    op.drop_table("data_gap_records")
    op.drop_table("candle_records")
