"""Add explicit ON DELETE semantics to all foreign keys.

Every ForeignKey must specify its referential integrity action so the
database enforces deletion rules deterministically.

CASCADE FKs (child wholly owned by parent — delete parent deletes children):
  - strategy_builds.strategy_id → strategies
  - trials.run_id → runs
  - artifacts.run_id → runs
  - feed_health_events.feed_id → feeds
  - override_watermarks.override_id → overrides

RESTRICT FKs (prevent deletion of referenced parent — 25 remaining FKs):
  All audit-trail actor columns (*_by, *_id → users) and cross-entity
  reference columns.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-06 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# FK definitions: (table, column, referred_table, ondelete)
# ---------------------------------------------------------------------------

_FK_UPDATES: list[tuple[str, str, str, str]] = [
    # CASCADE — child wholly owned by parent
    ("strategy_builds", "strategy_id", "strategies", "CASCADE"),
    ("trials", "run_id", "runs", "CASCADE"),
    ("artifacts", "run_id", "runs", "CASCADE"),
    ("feed_health_events", "feed_id", "feeds", "CASCADE"),
    ("override_watermarks", "override_id", "overrides", "CASCADE"),
    # RESTRICT — audit trail and cross-entity references
    ("strategies", "created_by", "users", "RESTRICT"),
    ("candidates", "strategy_id", "strategies", "RESTRICT"),
    ("candidates", "submitted_by", "users", "RESTRICT"),
    ("deployments", "strategy_id", "strategies", "RESTRICT"),
    ("deployments", "deployed_by", "users", "RESTRICT"),
    ("runs", "strategy_id", "strategies", "RESTRICT"),
    ("overrides", "submitter_id", "users", "RESTRICT"),
    ("overrides", "reviewer_id", "users", "RESTRICT"),
    ("overrides", "applied_by", "users", "RESTRICT"),
    ("approval_requests", "candidate_id", "candidates", "RESTRICT"),
    ("approval_requests", "requested_by", "users", "RESTRICT"),
    ("approval_requests", "reviewer_id", "users", "RESTRICT"),
    ("draft_autosaves", "user_id", "users", "RESTRICT"),
    ("draft_autosaves", "strategy_id", "strategies", "RESTRICT"),
    ("chart_cache_entries", "run_id", "runs", "RESTRICT"),
    ("parity_events", "feed_id", "feeds", "RESTRICT"),
    ("parity_events", "reference_feed_id", "feeds", "RESTRICT"),
    ("certification_events", "feed_id", "feeds", "RESTRICT"),
    ("certification_events", "run_id", "runs", "RESTRICT"),
    ("refresh_tokens", "user_id", "users", "RESTRICT"),
    ("symbol_lineage_entries", "feed_id", "feeds", "RESTRICT"),
    ("symbol_lineage_entries", "run_id", "runs", "RESTRICT"),
    ("promotion_requests", "candidate_id", "candidates", "RESTRICT"),
    ("promotion_requests", "requester_id", "users", "RESTRICT"),
    ("promotion_requests", "reviewer_id", "users", "RESTRICT"),
]


def _fk_constraint_name(table: str, column: str) -> str:
    """Generate the conventional FK constraint name."""
    return f"fk_{table}_{column}"


def upgrade() -> None:
    """Replace default FK constraints with explicit ON DELETE actions."""
    for table, column, referred_table, ondelete in _FK_UPDATES:
        # Drop the existing unnamed/default FK
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(
                _fk_constraint_name(table, column),
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                _fk_constraint_name(table, column),
                referred_table,
                [column],
                ["id"],
                ondelete=ondelete,
            )


def downgrade() -> None:
    """Revert FK constraints to default (no ON DELETE action)."""
    for table, column, referred_table, _ondelete in reversed(_FK_UPDATES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(
                _fk_constraint_name(table, column),
                type_="foreignkey",
            )
            batch_op.create_foreign_key(
                _fk_constraint_name(table, column),
                referred_table,
                [column],
                ["id"],
            )
