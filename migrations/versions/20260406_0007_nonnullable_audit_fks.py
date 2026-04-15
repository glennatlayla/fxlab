"""Make audit-trail foreign keys NOT NULL.

Every mutation in the system must have a traceable actor — a SOC 2 compliance
requirement. The following user-reference columns previously allowed NULL, which
would permit rows with no recorded actor:

  - strategies.created_by
  - candidates.submitted_by
  - deployments.deployed_by
  - overrides.submitter_id
  - approval_requests.requested_by
  - promotion_requests.requester_id

This migration sets all six columns to NOT NULL. Existing NULL values must be
back-filled before running this migration (see data-fix runbook if applicable).

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Columns to make NOT NULL: (table_name, column_name)
# ---------------------------------------------------------------------------

_COLUMNS: list[tuple[str, str]] = [
    ("strategies", "created_by"),
    ("candidates", "submitted_by"),
    ("deployments", "deployed_by"),
    ("overrides", "submitter_id"),
    ("approval_requests", "requested_by"),
    ("promotion_requests", "requester_id"),
]


def upgrade() -> None:
    """Set audit-trail FK columns to NOT NULL."""
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(26),
            nullable=False,
        )


def downgrade() -> None:
    """Revert audit-trail FK columns to nullable."""
    for table, column in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.String(26),
            nullable=True,
        )
