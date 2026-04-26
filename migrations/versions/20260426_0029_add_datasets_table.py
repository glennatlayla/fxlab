"""Add datasets catalog table (M4.E3 — DatasetService backing store).

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-26

The ``datasets`` table is the persistent catalog the M4.E3
:class:`DatasetService` reads from and writes to. It replaces the
M2.C2 :class:`InMemoryDatasetResolver` whose state died with the
process. Each row is the canonical descriptor for one dataset_ref
the experiment plans can name in ``data_selection.dataset_ref``.

Columns:
- id: ULID primary key (26-char string).
- dataset_ref: Human-readable catalog reference, UNIQUE.
- symbols: JSON-encoded list of symbol strings.
- timeframe: Bar resolution (``"15m"``, ``"1h"``, ``"4h"``, ``"1d"``).
- source: Provider tag (``"oanda"``, ``"alpaca"``, ``"synthetic"``...).
- version: Catalog version string (``"v1"``, ``"v3"``...).
- is_certified: Boolean — has the dataset cleared the cert gate?
- created_by: Soft FK to users.id (NULLABLE — bootstrap entries
  have no creator). ON DELETE SET NULL so deleting a user does not
  cascade-delete catalog history.
- created_at, updated_at: TimestampMixin columns.

Constraints / indexes:
- UNIQUE(dataset_ref): the lookup key.
- INDEX(source, version): admin / operator filtering.
- INDEX(created_by): FK index (LL-S007 — every FK gets an index).
- INDEX(dataset_ref): redundant with UNIQUE on most engines but kept
  explicit so SQLite (which does not auto-index unique constraints
  the same way as Postgres) still sees the index.

Safety implications:
- The catalog is the single source of truth for dataset_ref →
  ResolvedDataset mapping. Losing rows here breaks experiment-plan
  resolution.
- The certification gate consumes ``is_certified`` directly. Inserts
  default to FALSE so a freshly-registered dataset cannot accidentally
  satisfy the gate.

Downgrade simply drops the table; the in-memory resolver
remains available for tests but is explicitly excluded from
production wiring (see services/api/main.py).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the ``datasets`` table with its UNIQUE + composite indexes."""
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column("dataset_ref", sa.String(128), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "is_certified",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_by",
            sa.String(26),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("dataset_ref", name="uq_datasets_dataset_ref"),
    )

    op.create_index(
        "ix_datasets_dataset_ref",
        "datasets",
        ["dataset_ref"],
    )
    op.create_index(
        "ix_datasets_source_version",
        "datasets",
        ["source", "version"],
    )
    op.create_index(
        "ix_datasets_created_by",
        "datasets",
        ["created_by"],
    )


def downgrade() -> None:
    """Drop the ``datasets`` table and its indexes."""
    op.drop_index("ix_datasets_created_by", table_name="datasets")
    op.drop_index("ix_datasets_source_version", table_name="datasets")
    op.drop_index("ix_datasets_dataset_ref", table_name="datasets")
    op.drop_table("datasets")
