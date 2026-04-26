"""Add row_version column to runs and overrides tables for optimistic locking.

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-26

Same class of bug fixed for the strategies table in migration 0026.
The Run and Override ORM models in libs/contracts/models.py both
declare::

    row_version: Any = Column(Integer, nullable=False,
                               default=1, server_default="1")

Their respective Sql*Repository classes increment row_version on
every UPDATE for optimistic-concurrency-control. The unit suite
(sqlite, schema bootstrapped via create_all() from the ORM models)
silently picks up the column, so unit tests pass against the model
declarations.

The ALEMBIC schema, however, never had these columns — neither the
initial 0001 migration's `runs` and `overrides` CREATE TABLEs nor
any follow-up migration added them. The omission stayed invisible
because:
  - Unit tests use sqlite + create_all() — they get the column
    from the ORM model, not the migration chain.
  - The migrations-postgres CI job validates only the migration
    upgrade->downgrade->upgrade round-trip, not the application
    queries against the resulting schema.

The new "Integration tests (docker compose)" job introduced in
commit 0c1241f is the first CI gate that runs the actual API code
against a real, alembic-migrated Postgres. After 0026 fixed the
strategies side, the same job surfaced::

    psycopg2.errors.UndefinedColumn:
        column "row_version" of relation "overrides" does not exist

and a parallel issue on `runs` whose Sql repository also bumps
row_version.

This migration brings both tables' alembic schema into agreement
with the ORM models + repository code:

  ALTER TABLE runs      ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1
  ALTER TABLE overrides ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1

Pattern is identical to 20260412_0014_add_order_row_version.py
(orders) and 20260426_0026_add_strategy_row_version.py (strategies).
Existing rows backfill to 1 via server_default, matching the ORM's
``default=1`` behaviour for new inserts.

Safety implications:
- Existing rows backfilled to ``1`` before NOT NULL applies.
  Safe: every existing run/override was written without a
  row_version, so post-migration value of ``1`` matches what the
  ORM default would have produced on insert.
- DDL is identical on SQLite (test) and PostgreSQL (prod), so the
  unit suite stays green.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add row_version INTEGER NOT NULL DEFAULT 1 to runs and overrides tables."""
    op.add_column(
        "runs",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "overrides",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    """Remove row_version column from runs and overrides tables."""
    op.drop_column("overrides", "row_version")
    op.drop_column("runs", "row_version")
