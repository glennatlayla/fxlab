"""Add row_version column to orders table for optimistic locking.

Without optimistic locking, concurrent workers (e.g. a fill update and a
cancel request) can silently overwrite each other's status changes. The
row_version column enables detect-and-reject semantics: every update bumps
the version, and the SqlOrderRepository checks the expected version before
writing.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-12
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """Add row_version INTEGER NOT NULL DEFAULT 1 to orders table."""
    op.add_column(
        "orders",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove row_version column from orders table."""
    op.drop_column("orders", "row_version")
