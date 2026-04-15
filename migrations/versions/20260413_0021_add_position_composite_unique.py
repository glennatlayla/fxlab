"""Add composite unique constraint on positions(deployment_id, symbol).

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-13

Adds a composite unique constraint on positions(deployment_id, symbol) to
prevent duplicate position records for the same deployment+symbol combination.

Without this constraint, multiple position records for the same symbol in the
same deployment could exist, causing silent data corruption where the most
recent write would overwrite historical data without audit trail, and position
queries might return inconsistent state.

The constraint also includes a composite index for efficient queries on
(deployment_id, symbol) pairs.

Safety implications:
- Protects against misconfigured services that insert multiple position
  records for the same deployment+symbol.
- Ensures position state is deterministic and queryable by deployment+symbol.
- Provides fast lookups via the composite index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite unique constraint and index on positions."""
    # Add composite index for query efficiency
    op.create_index(
        "ix_positions_deployment_symbol",
        "positions",
        ["deployment_id", "symbol"],
        if_not_exists=True,
    )

    # Add composite unique constraint to prevent duplicate position records
    op.create_unique_constraint(
        "uq_positions_deployment_symbol",
        "positions",
        ["deployment_id", "symbol"],
        if_not_exists=True,
    )


def downgrade() -> None:
    """Remove composite unique constraint and index on positions."""
    op.drop_constraint(
        "uq_positions_deployment_symbol",
        "positions",
        type_="unique",
    )

    op.drop_index(
        "ix_positions_deployment_symbol",
        table_name="positions",
    )
