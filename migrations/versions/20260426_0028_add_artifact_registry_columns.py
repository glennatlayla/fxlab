"""Add subject_id / storage_path / created_by columns to artifacts table.

Revision ID: 0028
Revises: 0027
Create Date: 2026-04-26

Reconciles a long-standing ORM/contract divergence on the ``artifacts``
table.

Two parallel field-naming conventions accumulated over time:

* The original M2 schema (migration 0001) shipped ``run_id`` (FK to
  ``runs``) + ``uri`` + ``checksum``.
* The M5 artifact-registry contract in
  ``libs/contracts/artifact.py`` defines ``subject_id`` +
  ``storage_path`` + ``created_by`` and is what the
  ``SqlArtifactRepository`` reads/writes against. The download route
  (``services/api/routes/artifacts.py``) consumes
  ``artifact.storage_path`` — it is part of the API surface.

Until now the ORM model only declared the legacy columns, which meant
the SQL repository compiled but blew up at runtime against any real
Postgres / SQLite database with::

    AttributeError: 'Artifact' object has no attribute 'subject_id'

The integration suite (commit 5ce37f8) caught this and xfailed the
entire ``TestSqlArtifactRepository`` class. This migration removes
that xfail by bringing the schema into agreement with the contract
the repository expects.

Design choice:

* New columns are NULLABLE so existing rows (written through the
  legacy ``run_id`` / ``uri`` path, e.g. by ``test_m2_db_schema`` and
  ``test_stub_replacements``) remain valid without a backfill step.
* The Pydantic ``Artifact`` contract enforces non-null at the
  application boundary, so any code path going through the registry
  cannot insert a NULL ``storage_path`` regardless of the column's
  database-level nullability.
* ``uri`` is also relaxed to NULLABLE in the same step so registry
  inserts that supply ``storage_path`` (and skip ``uri``) do not
  violate the old NOT NULL.
* ``created_by`` is a soft FK to ``users.id`` with ``ON DELETE SET
  NULL`` — losing the creator should not cascade-delete artifact
  history.
* ``subject_id`` is indexed because the registry list-query filters
  on it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add registry-style columns and relax legacy ``uri`` to NULLABLE.

    Schema delta on ``artifacts``::

        ALTER COLUMN uri          DROP NOT NULL
        ADD COLUMN  subject_id    VARCHAR(26)  NULL
        ADD COLUMN  storage_path  VARCHAR(512) NULL
        ADD COLUMN  created_by    VARCHAR(26)  NULL  REFERENCES users(id)
                                                     ON DELETE SET NULL
        CREATE INDEX ix_artifacts_subject_id  ON artifacts(subject_id)
        CREATE INDEX ix_artifacts_created_by  ON artifacts(created_by)
    """
    # Relax the legacy `uri` column. Required so registry-shaped inserts
    # (which populate storage_path instead) don't trip the old NOT NULL.
    # alter_column is a no-op-on-nullable on SQLite via batch mode.
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column("uri", existing_type=sa.String(512), nullable=True)
        batch_op.add_column(sa.Column("subject_id", sa.String(26), nullable=True))
        batch_op.add_column(sa.Column("storage_path", sa.String(512), nullable=True))
        batch_op.add_column(
            sa.Column(
                "created_by",
                sa.String(26),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )

    op.create_index("ix_artifacts_subject_id", "artifacts", ["subject_id"])
    op.create_index("ix_artifacts_created_by", "artifacts", ["created_by"])


def downgrade() -> None:
    """Reverse upgrade(): drop new columns/indexes, restore ``uri`` NOT NULL.

    The NOT NULL restoration assumes any row inserted via the registry
    path has been backfilled with a ``uri`` value (or such rows have
    been migrated/removed) before the downgrade runs. In dev/test this
    is a non-issue because every test run starts from a clean schema.
    """
    op.drop_index("ix_artifacts_created_by", table_name="artifacts")
    op.drop_index("ix_artifacts_subject_id", table_name="artifacts")

    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.drop_column("created_by")
        batch_op.drop_column("storage_path")
        batch_op.drop_column("subject_id")
        batch_op.alter_column("uri", existing_type=sa.String(512), nullable=False)
