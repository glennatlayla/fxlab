"""Add source column to strategies table for IR vs draft-form provenance.

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-25

Adds a non-null ``source`` VARCHAR(32) column to ``strategies`` to record
how each strategy was authored:

- ``"draft_form"`` — the legacy Strategy Studio wizard (existing rows
  default here so the historical surface keeps working unchanged).
- ``"ir_upload"`` — created via ``POST /strategies/import-ir``
  (M2.C1; this migration's reason for existing).

Locked default 5 in the M2 workplan ("Coexistence with draft-form
strategies") requires both sources to coexist in a single ``strategies``
table, distinguished by this flag. M2.C4's ``GET /strategies/{id}``
returns ``source`` so the frontend renders the correct view.

A CHECK constraint pins the allowed values so a typo in the calling
code surfaces at write-time, not silently at render-time.

Safety implications:
- Existing rows are backfilled to ``"draft_form"`` via ``server_default``
  before the column is set NOT NULL. This is safe because every existing
  strategy in production was authored through the draft-form flow — there
  was no other path until this migration lands.
- The CHECK constraint covers SQLite (test) and PostgreSQL (prod)
  identically.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``source`` column with backfill default and CHECK constraint."""
    op.add_column(
        "strategies",
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="draft_form",
        ),
    )
    op.create_check_constraint(
        "chk_strategies_source",
        "strategies",
        "source IN ('draft_form', 'ir_upload')",
    )


def downgrade() -> None:
    """Remove the ``source`` column and its CHECK constraint."""
    op.drop_constraint("chk_strategies_source", "strategies", type_="check")
    op.drop_column("strategies", "source")
