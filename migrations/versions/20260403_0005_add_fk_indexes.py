"""Add missing foreign key indexes for unindexed ForeignKey columns.

Foreign keys without indexes can cause full table scans during JOIN operations
and ON DELETE CASCADE operations. This migration adds indexes to 6 unindexed
foreign key columns identified in the schema review:

- candidates.submitted_by → users.id (missing index)
- deployments.deployed_by → users.id (missing index)
- parity_events.reference_feed_id → feeds.id (missing index)
- overrides.submitter_id → users.id (missing index)
- overrides.reviewer_id → users.id (missing index)
- overrides.applied_by → users.id (missing index)

Note: candidates.strategy_id, deployments.strategy_id already have indexes
from models.py. Similarly, feeds.id FK relationships are indexed where needed.
The candidates table has submitted_by but not created_by (created_by is on
the strategies table, which already has its own index).

This improves query performance for:
1. Foreign key constraint enforcement at DELETE time.
2. Reverse lookups (find all candidates for a user).
3. Audit and traceability queries filtering by actor/operator IDs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create missing indexes on unindexed foreign key columns."""
    # Candidates table — submitted_by FK is unindexed
    # Note: candidates does NOT have a created_by column (that's on strategies)
    op.create_index("ix_candidates_submitted_by", "candidates", ["submitted_by"])

    # Deployments table — deployed_by FK is unindexed
    op.create_index("ix_deployments_deployed_by", "deployments", ["deployed_by"])

    # ParityEvents table — reference_feed_id FK is unindexed
    op.create_index("ix_parity_events_reference_feed_id", "parity_events", ["reference_feed_id"])

    # Overrides table — submitter_id, reviewer_id, applied_by FKs are unindexed
    op.create_index("ix_overrides_submitter_id", "overrides", ["submitter_id"])
    op.create_index("ix_overrides_reviewer_id", "overrides", ["reviewer_id"])
    op.create_index("ix_overrides_applied_by", "overrides", ["applied_by"])


def downgrade() -> None:
    """Drop all created indexes."""
    op.drop_index("ix_candidates_submitted_by", "candidates")
    op.drop_index("ix_deployments_deployed_by", "deployments")
    op.drop_index("ix_parity_events_reference_feed_id", "parity_events")
    op.drop_index("ix_overrides_submitter_id", "overrides")
    op.drop_index("ix_overrides_reviewer_id", "overrides")
    op.drop_index("ix_overrides_applied_by", "overrides")
