"""Add row_version column to strategies table for optimistic locking.

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-26

The Strategy ORM model in libs/contracts/models.py declares::

    row_version: Any = Column(Integer, nullable=False,
                               default=1, server_default="1")

and SqlStrategyRepository increments it on every UPDATE for
optimistic-concurrency-control. The unit test suite (sqlite, schema
bootstrapped via create_all() from the ORM models) silently picks up
the column, so unit tests pass against the model declaration.

The ALEMBIC schema, however, never had this column — the initial
0001 migration's strategies CREATE TABLE didn't include it, and
no follow-up migration added it. The omission stayed invisible
because the only CI gate against real Postgres before today
(migrations-postgres) only validates the migration round-trip, not
the application's queries against the resulting schema.

The new "Integration tests (docker compose)" job introduced in
commit 0c1241f is the first CI gate that runs the actual API code
against a real, alembic-migrated Postgres. It immediately surfaced
this gap with::

    psycopg2.errors.UndefinedColumn:
        column "row_version" of relation "strategies" does not exist

This migration brings the schema into agreement with the ORM model
and the repository code. The pattern matches the existing
20260412_0014_add_order_row_version.py which did the same fix for
the orders table when its row_version was added.

Safety implications:
- Existing rows are backfilled to ``1`` via server_default before
  the column is set NOT NULL. Safe: every existing strategy was
  written without a row_version, so the post-migration value of
  ``1`` matches what the ORM default would have produced on insert.
- Both SQLite (test) and PostgreSQL (prod) accept the same DDL,
  so the unit suite stays green and integration tests start
  passing.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add row_version INTEGER NOT NULL DEFAULT 1 to strategies table."""
    op.add_column(
        "strategies",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove row_version column from strategies table."""
    op.drop_column("strategies", "row_version")
