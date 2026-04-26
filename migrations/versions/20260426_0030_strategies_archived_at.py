"""Add archived_at column + btree index to strategies for soft-archive lifecycle.

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-26

The Strategy ORM model in ``libs/contracts/models.py`` declares::

    archived_at: Any = Column(DateTime(timezone=True), nullable=True)

with a btree index named ``ix_strategies_archived_at``. The new
``StrategyService.archive_strategy`` / ``restore_strategy`` methods
read and write this column to soft-retire strategies without losing
referential integrity (run history, audit trail, deployments still
point at the strategy row).

A NULL value means the strategy is in the active catalogue. A
non-NULL value is the UTC timestamp at which the operator clicked
Archive. The list endpoint filters ``archived_at IS NULL`` by
default — the index keeps that scan O(matches) instead of O(rows)
on a growing strategies table.

Design choice — why no parallel ``is_archived`` Boolean column:

* Two sources of truth for the same fact (``is_archived``,
  ``archived_at IS NOT NULL``) drift apart. We keep one column,
  the timestamp, and derive the boolean downstream.
* The Pydantic contract on the wire is ``archived_at: str | None``
  so the frontend renders the "Archived" badge from the same field
  it would use to display the archive date.

Idempotency:

* Both upgrade and downgrade introspect the existing schema before
  issuing DDL. Running ``upgrade`` twice in a row is a no-op the
  second time. Running ``downgrade`` against a schema that already
  lacks the column / index is also a no-op. This matches the
  defensive pattern already in the migrations directory and keeps
  the round-trip CI job idempotent on partially-migrated test
  databases.

Safety implications:

* New column is NULLABLE so existing rows (every strategy created
  before this migration) keep meaning "active" without a backfill
  step.
* The downgrade drops the column. Any existing archive data is
  permanently lost on a downgrade — acceptable here because the
  feature is brand-new in this release and no production rows
  carry archive history yet. Future re-archives can re-set the
  column on a fresh upgrade.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# Revision identifiers used by Alembic.
revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "strategies"
_COLUMN_NAME = "archived_at"
_INDEX_NAME = "ix_strategies_archived_at"


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    """Return True if ``table`` already has ``column`` in the current schema."""
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    """Return True if ``table`` already has an index named ``index_name``."""
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table))


def upgrade() -> None:
    """Add ``archived_at TIMESTAMP WITH TIME ZONE NULL`` and its btree index.

    Idempotent: introspects the live schema first so re-running on a
    partially-applied database does not raise DuplicateColumn.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_column(inspector, _TABLE_NAME, _COLUMN_NAME):
        op.add_column(
            _TABLE_NAME,
            sa.Column(
                _COLUMN_NAME,
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        # Re-inspect so the index check below sees the new column on
        # backends that cache reflection state per-inspector.
        inspector = inspect(bind)

    if not _has_index(inspector, _TABLE_NAME, _INDEX_NAME):
        op.create_index(_INDEX_NAME, _TABLE_NAME, [_COLUMN_NAME])


def downgrade() -> None:
    """Drop the index and column added by :func:`upgrade`.

    Idempotent: introspects the live schema first so re-running on a
    partially-rolled-back database does not raise UndefinedColumn /
    UndefinedObject for the index.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_index(inspector, _TABLE_NAME, _INDEX_NAME):
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
        inspector = inspect(bind)

    if _has_column(inspector, _TABLE_NAME, _COLUMN_NAME):
        # batch_alter_table makes drop_column work on SQLite (which does
        # not natively support ALTER TABLE ... DROP COLUMN before 3.35).
        with op.batch_alter_table(_TABLE_NAME) as batch_op:
            batch_op.drop_column(_COLUMN_NAME)
