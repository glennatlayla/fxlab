"""Add alert_notifications table for Alertmanager webhook receiver.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-15

The alert_notifications table is an append-only log of every alert delivered
to the FXLab API by Prometheus Alertmanager. It backs the
``POST /observability/alert-webhook`` endpoint.

Columns:
- id: ULID primary key assigned by the ingest service (40 chars).
- fingerprint: Alertmanager stable alert identifier (indexed).
- status: 'firing' or 'resolved' (indexed, CHECK-constrained).
- alertname: labels['alertname'] flattened (indexed, default '').
- severity: labels['severity'] flattened (indexed, default '').
- starts_at: alert start time (indexed).
- ends_at: alert end time (nullable; NULL while firing).
- labels: full Alertmanager label map (JSON).
- annotations: full Alertmanager annotation map (JSON).
- generator_url: Prometheus URL that generated the alert.
- receiver: Alertmanager receiver name (e.g. 'critical_webhook').
- external_url: Alertmanager external URL.
- group_key: Alertmanager group_key (stable per group).
- received_at: server-side receipt time (indexed, default now()).

Indexing rationale:
- fingerprint, alertname, severity, status: required for operator dashboards
  and incident post-mortems that filter the log by specific alert.
- starts_at and received_at: required for time-range queries (the two most
  common patterns — alerts that started in a window, alerts we received in
  a window).

Safety implications:
- Append-only — no unique constraints that would reject retries from
  Alertmanager's repeat_interval (which is a deliberate, meaningful behaviour).
- Dialect-aware BOOLEAN defaults are not needed here (no boolean columns) but
  this migration is still validated by the round-trip CI gate.
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Create alert_notifications table and its indexes."""
    op.create_table(
        "alert_notifications",
        sa.Column("id", sa.String(40), primary_key=True, nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("alertname", sa.String(256), nullable=False, server_default=""),
        sa.Column("severity", sa.String(32), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("generator_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("receiver", sa.String(256), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('firing', 'resolved')",
            name="chk_alert_notifications_status",
        ),
    )
    op.create_index(
        "ix_alert_notifications_fingerprint",
        "alert_notifications",
        ["fingerprint"],
    )
    op.create_index(
        "ix_alert_notifications_status",
        "alert_notifications",
        ["status"],
    )
    op.create_index(
        "ix_alert_notifications_alertname",
        "alert_notifications",
        ["alertname"],
    )
    op.create_index(
        "ix_alert_notifications_severity",
        "alert_notifications",
        ["severity"],
    )
    op.create_index(
        "ix_alert_notifications_starts_at",
        "alert_notifications",
        ["starts_at"],
    )
    op.create_index(
        "ix_alert_notifications_received_at",
        "alert_notifications",
        ["received_at"],
    )


def downgrade() -> None:
    """Drop alert_notifications table and all its indexes."""
    op.drop_index(
        "ix_alert_notifications_received_at",
        table_name="alert_notifications",
    )
    op.drop_index(
        "ix_alert_notifications_starts_at",
        table_name="alert_notifications",
    )
    op.drop_index(
        "ix_alert_notifications_severity",
        table_name="alert_notifications",
    )
    op.drop_index(
        "ix_alert_notifications_alertname",
        table_name="alert_notifications",
    )
    op.drop_index(
        "ix_alert_notifications_status",
        table_name="alert_notifications",
    )
    op.drop_index(
        "ix_alert_notifications_fingerprint",
        table_name="alert_notifications",
    )
    op.drop_table("alert_notifications")
