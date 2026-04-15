"""
Add source column to audit_events table for BE-07: Audit Source Tracking.

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-13

Adds a nullable source VARCHAR(32) column to track which client initiated
each audit event (web-desktop, web-mobile, api). Nullable for backwards
compatibility with existing audit events.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source column to audit_events table."""
    op.add_column("audit_events", sa.Column("source", sa.String(32), nullable=True))


def downgrade() -> None:
    """Remove source column from audit_events table."""
    op.drop_column("audit_events", "source")
