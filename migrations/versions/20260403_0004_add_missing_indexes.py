"""Add missing indexes for production query patterns.

Adds indexes to 11 columns across 6 tables that are commonly filtered on:
- feeds.feed_type
- audit_events.actor, audit_events.action
- approval_requests.requested_by, approval_requests.reviewer_id
- certification_events.certification_type
- symbol_lineage_entries.feed_id, symbol_lineage_entries.run_id
- promotion_requests.requester_id, promotion_requests.reviewer_id

These indexes improve query performance for filtering and lookups in production
query patterns.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create missing indexes on production query pattern columns."""
    op.create_index("ix_feeds_feed_type", "feeds", ["feed_type"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_approval_requests_requested_by", "approval_requests", ["requested_by"])
    op.create_index("ix_approval_requests_reviewer_id", "approval_requests", ["reviewer_id"])
    op.create_index(
        "ix_certification_events_certification_type",
        "certification_events",
        ["certification_type"],
    )
    op.create_index(
        "ix_symbol_lineage_entries_feed_id", "symbol_lineage_entries", ["feed_id"]
    )
    op.create_index(
        "ix_symbol_lineage_entries_run_id", "symbol_lineage_entries", ["run_id"]
    )
    op.create_index(
        "ix_promotion_requests_requester_id", "promotion_requests", ["requester_id"]
    )
    op.create_index(
        "ix_promotion_requests_reviewer_id", "promotion_requests", ["reviewer_id"]
    )


def downgrade() -> None:
    """Drop all created indexes."""
    op.drop_index("ix_feeds_feed_type", "feeds")
    op.drop_index("ix_audit_events_actor", "audit_events")
    op.drop_index("ix_audit_events_action", "audit_events")
    op.drop_index("ix_approval_requests_requested_by", "approval_requests")
    op.drop_index("ix_approval_requests_reviewer_id", "approval_requests")
    op.drop_index(
        "ix_certification_events_certification_type", "certification_events"
    )
    op.drop_index(
        "ix_symbol_lineage_entries_feed_id", "symbol_lineage_entries"
    )
    op.drop_index(
        "ix_symbol_lineage_entries_run_id", "symbol_lineage_entries"
    )
    op.drop_index(
        "ix_promotion_requests_requester_id", "promotion_requests"
    )
    op.drop_index(
        "ix_promotion_requests_reviewer_id", "promotion_requests"
    )
